from flask import Flask, render_template, request, jsonify
import os, time
import base64
import hashlib
import yaml
import threading
from Crypto.Cipher import AES

app = Flask(__name__)

baseImageId = '539c2be37d94' # kasm-1.14.0 이미지 - test 서버 
#baseImageId = '' # kasm-1.14.0 이미지 - 실서버
#baseImageId = '1692c5f95a70e' # 로컬 이미지

BS = 16
pad = (lambda s: s + (BS - len(s) % BS) * chr(BS - len(s) % BS).encode())
unpad = (lambda s: s[:-ord(s[len(s)-1:])])

extractNodeInfos = dict()
extractPodInfos = dict()
extractNodeCPUs = dict()

# pv pod 만드는 함수
def generatePVPodYaml(pvName, storageClassName, pathName) : 
    PVDefinition = {
        "apiVersion": "v1",
        "kind": "PersistentVolume",
        "metadata": {"name": pvName}, 
        "spec": {
            "capacity": {
                "storage": "500Mi",
            },
            "volumeMode": "Filesystem",
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": storageClassName,
            "persistentVolumeReclaimPolicy": "Delete",
            "hostPath": {
                "path": "/tmp/backup/"+pathName
            }
        }
    }

    # YAML로 변환하여 문자열로 반환합니다.
    PVYaml = yaml.dump(PVDefinition, default_flow_style=False)

    return PVYaml

# pvc pod 만드는 함수
def generatePVCPodYaml(pvcName, storageClassName) : 
    PVCDefinition = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {"name": pvcName}, 
        "spec": {
            "volumeMode": "Filesystem",
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": storageClassName,
            "resources": {
                "requests": {
                    "storage": "500Mi"
                }
            }
        }
    }

    # YAML로 변환하여 문자열로 반환합니다.
    PVCYaml = yaml.dump(PVCDefinition, default_flow_style=False)

    return PVCYaml

# deployment pod 만드는 함수
def generateDeploymentPodYaml(deploymentName, containerName, imageName, servicePort, pathName, volumeName, pvcName) : 
    deploymentDefinition = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": deploymentName}, 
        "spec": {
            "replicas": 1,
            "selector": {
                "matchLabels": {
                    "app": "webdesktop", # service에서 pod를 선택할 때 구별하는 용도 
                    "port": str(servicePort) # port label 추가
                }
            },
            "template": {
                "metadata": {
                    "labels": {
                        "app": "webdesktop", # 새로운 pod가 생성될 때 template 정의 
                        "port": str(servicePort) # port label 추가 
                    }
                },
                "spec": { 
                    "containers": [ 
                        {
                            "name": containerName, 
                            "image": imageName, 
                            "ports": [{"containerPort": 6901}], # container 포트는 이미지 받을 때부터 열려있었던 포트인 6901로 접속해야 가능 
                            "volumeMounts": [{
                                "mountPath": "/var/backups/"+pathName,
                                "name": volumeName    
                            }]
                        } 
                    ], 
                    "imagePullSecrets": [{"name": "harbor"}], # harbor라는 이름의 kubeconfig.yaml 파일 
                    "volumes": [{
                        "name": volumeName,
                        "persistentVolumeClaim": {
                            "claimName": pvcName
                        }
                    }]
                }
            }
        }
    }

    # YAML로 변환하여 문자열로 반환합니다.
    deploymentYaml = yaml.dump(deploymentDefinition, default_flow_style=False)

    return deploymentYaml

# deployment pod 만드는 함수
def generateLoadDeploymentPodYaml(deploymentName, containerName, imageName, servicePort, pathName, volumeName, pvcName) : 
    deploymentDefinition = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": deploymentName}, 
        "spec": {
            "replicas": 1,
            "selector": {
                "matchLabels": {
                    "app": "webdesktop", # service에서 pod를 선택할 때 구별하는 용도 
                    "port": str(servicePort) # port label 추가
                }
            },
            "template": {
                "metadata": {
                    "labels": {
                        "app": "webdesktop", # 새로운 pod가 생성될 때 template 정의 
                        "port": str(servicePort) # port label 추가 
                    }
                },
                "spec": { 
                    "containers": [ 
                        {
                            "name": containerName, 
                            "image": imageName, 
                            "ports": [{"containerPort": 6901}], # container 포트는 이미지 받을 때부터 열려있었던 포트인 6901로 접속해야 가능 
                            "volumeMounts": [{
                                "mountPath": "/var/backups/"+pathName,
                                "name": volumeName    
                            }],
                            "command": ["/bin/bash", "-ec", "while :; do echo '.'; sleep 5; done"]
                        } 
                    ], 
                    "imagePullSecrets": [{"name": "harbor"}], # harbor라는 이름의 kubeconfig.yaml 파일 
                    "volumes": [{
                        "name": volumeName,
                        "persistentVolumeClaim": {
                            "claimName": pvcName
                        }
                    }]
                }
            }
        }
    }

    # YAML로 변환하여 문자열로 반환합니다.
    deploymentYaml = yaml.dump(deploymentDefinition, default_flow_style=False)

    return deploymentYaml

# service pod를 만드는 함수 (pod를 외부로 노출하기 위함)
def generateServiceYaml(serviceName, servicePort, nodePort):
    # Service의 기본 구조를 딕셔너리로 정의합니다.
    serviceDefinition = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": serviceName},
        "spec": {
            "type": "NodePort",
            "selector": {
                "app": "webdesktop",
                "port": str(servicePort) # port label 추가
            },
            "ports": [
                {
                    "port": int(servicePort), 
                    "targetPort": 6901, # deployment의 containerPort와 일치해야 함 
                    "nodePort": int(nodePort) # node_port는 30000~32768 
                }
            ]
        }
    }

    # YAML로 변환하여 문자열로 반환합니다.
    serviceYaml = yaml.dump(serviceDefinition, default_flow_style=False)

    return serviceYaml

# node의 이름과 ip를 추출하기 위한 용도 
def extractNodeInfo():
    result = os.popen("kubectl get nodes -o wide --kubeconfig /root/kubeconfig.yml").read()

    print("result:", result)

    nodeInfoList = result.split('\n')[1:-1]

    print("nodeInfo: ", nodeInfoList)

    for nodeInfo in nodeInfoList: 
        node = nodeInfo.split() 
        nodeName, nodeExternalIp = node[0], node[6] 
        extractNodeInfos[nodeName] = nodeExternalIp 

    print("extractN: ", extractNodeInfos)

    return extractNodeInfos

# pod의 external ip를 알기 위한 함수 
def extractPodInfo():

    result = os.popen("kubectl get pods -o wide --kubeconfig /root/kubeconfig.yml").read()

    print("result:", result) 

    podInfoList = result.split('\n')[1:-1]

    print("podInfo: ", podInfoList)

    for podInfo in podInfoList: 
        pod = podInfo.split() 
        podName, nodeName = pod[0], pod[6] 
        extractPodInfos[podName] = nodeName

    return extractPodInfos

# pod의 external ip를 알기 위한 함수 
def extractNodeIpOfPod(nodeList):

    podList = extractPodInfo()

    for _, nodeName in podList.items():
        if nodeName in nodeList:
            return extractNodeInfos[nodeName]

    return "Not Found"


# Pod yaml로 생성하기 
def applyPodCmd(yamlFilePath):
    return "kubectl apply -f " + yamlFilePath + " --kubeconfig /root/kubeconfig.yml"

# label로 Pod 이름 조회하기
def getPodName(port) :
    return "kubectl get pod -l port="+port+" -o name --kubeconfig /root/kubeconfig.yml"

# pod 내부로 start.sh 복사하기
def copyScriptToPod(podName, containerName) :
    return "kubectl cp /home/ubuntu/start.sh "+podName+":/tmp/ -c "+containerName+" --kubeconfig /root/kubeconfig.yml"

# pv Pod 지우기  
def deletePVPodCmd(pvName): 
    return "kubectl delete pv " + pvName + " --kubeconfig /root/kubeconfig.yml"

# pvc Pod 지우기  
def deletePVCPodCmd(pvcName): 
    return "kubectl delete pvc " + pvcName + " --kubeconfig /root/kubeconfig.yml"

# deployment Pod 지우기  
def deleteDeployPodCmd(deploymentName): 
    return "kubectl delete deployment " + deploymentName + " --kubeconfig /root/kubeconfig.yml"

# service Pod 지우기  
def deleteServicePodCmd(serviceName): 
    return "kubectl delete service " + serviceName + " --kubeconfig /root/kubeconfig.yml"

# yaml 파일 지우기 
def deleteYamlFile(yamlFilePath):
    return "rm " + yamlFilePath

#===================
# pod namespace 가져오기 
def getPodNameSpace(podName):
    return f"kubectl get pod {podName} -o custom-columns=NAMESPACE:.metadata.namespace --no-headers --kubeconfig /root/kubeconfig.yml"

# yaml 파일 업데이트 함수 - deployment
def updateDeploymentYaml(deploymentName, namespace, deploymentYaml):
    print("d: "+deploymentName)
    print("n: "+ namespace)
    print("path: "+deploymentYaml)
    return f"kubectl get deployment {deploymentName} -n {namespace} -o yaml > {deploymentYaml} --kubeconfig /root/kubeconfig.yml"

# yaml 파일 업데이트 함수 - service 
def updateServiceYaml(serviceName, namespace, serviceYaml):
    print("s: "+serviceName)
    print("n: "+namespace)
    return f"kubectl get service {serviceName} -n {namespace} -o yaml > {serviceYaml} --kubeconfig /root/kubeconfig.yml"

# Dockerfile 작성함수 
def createDockerfile(baseImage, vmName):
    # Dockerfile 내용을 저장할 문자열 초기화
    dockerfileContent = f"FROM {baseImage}\n"
    
    # 파일 복사 명령 추가
    #volumeMount = f"VOLUME [{sourcePath}]\n"
    volumeMount = f"COPY /backup/{vmName} /home/kasm-user/\n"

    dockerfileContent += volumeMount

    # Dockerfile 내용 반환
    return dockerfileContent

# Dockerfile build 함수 
def buildDockerImage(imagePath, port, dockerFilePath, parentPath):
    os.popen(f"docker build -t {imagePath}:{port} -f {dockerFilePath} {parentPath}")
    return f"{imagePath}:{port}"

def deleteScript():
    return 

def deleteBackUpData():
    return

#=================

# 컨테이너 관련 명령어
def createContainerCmd(port, pwd, imageId) : # vm+port 이름의 컨테이너 생성
    vmname = "vm"+port
    return "docker create --shm-size=512m -p "+port+":6901 -e VNC_PW="+pwd+" --name "+vmname+" "+imageId

def startContainerCmd(containerId) :    # containerid로 컨테이너 실행 
    return "docker start "+containerId

def stopContainerCmd(containerId) :     # containerid로 컨테이너 중지
    return "docker stop "+containerId

def deleteContainerCmd(containerId) :   # containerid로 컨테이너 삭제
    return "docker rm -f "+containerId

def copyScriptToContainer(containerId) :
    return "docker cp /home/ubuntu/start.sh "+containerId+":/dockerstartup/"

def copyDesktopToContainer(containerId, vmName) :
    return "sudo docker cp /home/dockerFile/backup/"+vmName+"/Desktop/. "+containerId+":/home/kasm-user/Desktop/"

def changeVncScopeAndControl(containerId, scope, control, pwd) :
    return "docker exec -it --user root "+ containerId+" bash /dockerstartup/start.sh "+scope +" "+control+" "+pwd

# 이미지 관련 명령어
def createImgCmd(containerId, userId, port) : # registry.p2kcloud.com/base/userid:port 이름의 새로운 이미지 생성
    return "docker commit "+containerId+" registry.p2kcloud.com/base/"+userId+":"+port

def pushImgCmd(userId, port) :          # harbor에 이미지 저장
    return "docker push registry.p2kcloud.com/base/"+userId+":"+port

def pushImgCmdV2(dockerImage):
    return "docker push registry.p2kcloud.com/base/"+dockerImage

def deleteImgCmd(imageId) :             # imageid로 이미지 삭제
    return "docker rmi -f "+imageId

def pullImgCmd() :      # harbor에서 kasm 이미지 pull -> 이미 pull 받아짐
    return "docker pull registry.p2kcloud.com/base/vncdesktop"

class AESCipher(object):
    def __init__(self, key):
        self.key = hashlib.sha256(key.encode()).digest()

    def encrypt(self, message):
        message = message.encode()
        raw = pad(message)
        cipher = AES.new(self.key, AES.MODE_CBC, self.__iv().encode('utf8'))
        enc = cipher.encrypt(raw)
        return base64.b64encode(enc).decode('utf-8')

    def decrypt(self, enc):
        enc = base64.b64decode(enc)
        cipher = AES.new(self.key, AES.MODE_CBC, self.__iv().encode('utf8'))
        dec = cipher.decrypt(enc)
        return unpad(dec).decode('utf-8')

    def __iv(self):
        return chr(0) * 16

key = "thisiskey"
aes = AESCipher(key)

#=====================