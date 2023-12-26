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

# deployment pod 만드는 함수
def generateDeploymentPodYaml(deploymentName, containerName, imageName, servicePort) : 
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
                        } 
                    ], 
                    "imagePullSecrets": [{"name": "harbor"}] # harbor라는 이름의 kubeconfig.yaml 파일 
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

# deployment Pod 지우기  
def deleteDeployPodCmd(deploymentName): 
    return "kubectl delete deployment " + deploymentName + " --kubeconfig /root/kubeconfig.yml"

# service Pod 지우기  
def deleteServicePodCmd(serviceName): 
    return "kubectl delete service " + serviceName + " --kubeconfig /root/kubeconfig.yml"

# yaml 파일 지우기 
def deleteYamlFile(yamlFilePath):
    return "rm " + yamlFilePath

# Pod 백업 스크립트 작성 함수 
def createStopScript(containerName):

    # 백업 대상 Pod의 컨테이너 설정
    CONTAINERNAME = containerName
    
    # 중지 스크립트 내용 생성
    script = f"""#!/bin/bash

# 백업 대상 Pod와 컨테이너 설정
CONTAINERNAME="{CONTAINERNAME}"
CONTAINERID="$(docker ps -qf "name=$CONTAINERNAME")"

# 컨테이너 상태 중지 
docker stop $CONTAINERID 
"""

    return script

# Pod 백업 스크립트 작성 함수 
def createBackupScript(containerName, imagePath, port):

    # 백업 대상 Pod의 컨테이너 설정
    CONTAINERNAME = containerName
    IMAGEPATH = imagePath
    PORT = port
    
    # 백업 스크립트 내용 생성
    script = f"""#!/bin/bash

# 백업 대상 Pod와 컨테이너 설정
CONTAINERNAME="{CONTAINERNAME}"
CONTAINERID="$(docker ps -qf "name=$CONTAINERNAME")"
IMAGEPATH="{IMAGEPATH}"
PORT="{PORT}"



# 컨테이너 상태를 스냅샷으로 저장 
docker commit $CONTAINERID $IMAGEPATH:$PORT  
# 컨테이너 상태를 harbor로 저장 
docker push $IMAGEPATH:$PORT
"""

    return script


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
def createDockerfile(baseImage, sourcePath):
    # Dockerfile 내용을 저장할 문자열 초기화
    dockerfileContent = f"FROM {baseImage}\n"
    
    # 파일 복사 명령 추가
    volumeMount = f"VOLUME [{sourcePath}]\n"
    dockerfileContent += volumeMount

    # Dockerfile 내용 반환
    return dockerfileContent

# Dockerfile build 함수 
def buildDockerImage(userId, port, dockerFilePath):
    os.popen(f"docker build -t {userId}:{port} {dockerFilePath}")
    return f"{userId}:{port}"

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
    return "docker rm "+containerId

def copyScriptToContainer(containerId) :
    return "docker cp /home/ubuntu/start.sh "+containerId+":/dockerstartup/"

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

# spring 서버에서 컨테이너 생성 요청이 왔을 때, base 이미지로 컨테이너 생성하고 이미지 저장
@app.route('/create', methods=['POST']) 
def create(): 

    requestDTO = request.get_json()
    print("[create requestDTO] ", requestDTO)
    userId, port, pwd = str(requestDTO['id']), str(requestDTO['port']), str(requestDTO['password'])
    scope, control = str(requestDTO['scope']), str(requestDTO['control'])

    stream1 = os.popen(createContainerCmd(port, pwd, baseImageId))
    containerId = stream1.read()[:12]
    time.sleep(5)
    enContainerId = aes.encrypt(containerId) # containerId 암호화

    stream2 = os.popen(createImgCmd(containerId, userId, port))
    imageId = stream2.read()[7:20]
    enImageId = aes.encrypt(imageId)  # imageId 암호화
    vmName = "vm"+port
    scriptPath = "/dockerstartup/start.sh" 
    nodePort = str(requestDTO['nodePort']) 
    imagePath = str(requestDTO['imagePath'])

    os.popen(startContainerCmd(containerId))
    os.popen(copyScriptToContainer(containerId))
    os.popen(stopContainerCmd(containerId))

    # Depolyment yaml 파일 생성 
    deploymentPodYaml = generateDeploymentPodYaml(vmName, vmName, imagePath, port)
    deploymentFilePath = "/home/yaml/"+vmName+"Deployment.yaml"
    with open(deploymentFilePath, 'w') as deploymentYamlFile:
        deploymentYamlFile.write(deploymentPodYaml) 

    # Service yaml 파일 생성 
    servicePodYaml = generateServiceYaml(vmName, port, nodePort)
    serviceFilePath = "/home/yaml/"+vmName+"Service.yaml"
    with open(serviceFilePath, 'w') as serviceYamlFile:
        serviceYamlFile.write(servicePodYaml)

    print(deploymentPodYaml)
    print(servicePodYaml)

    os.popen(applyPodCmd(deploymentFilePath))
    os.popen(applyPodCmd(serviceFilePath))

    nodeList = extractNodeInfo()
    time.sleep(60)
    externalNodeIp = extractNodeIpOfPod(nodeList)

    print("nodes: ", nodeList)
    print("externalIp: ", externalNodeIp)

    response = {
            'port': port,
            'containerId' : enContainerId,
            'imageId' : enImageId,
            'externalNodeIp': externalNodeIp
        }

    return jsonify(response), 200



#spring 서버에서 가상환경 로드했을 때, 이미지로 컨테이너 생성 후 새로운 이미지로 저장
@app.route('/load', methods=['POST'])
def load() :

    requestDTO = request.get_json()
    print("[load requestDTO] ", requestDTO)
    userId, port, pwd, imageId = str(requestDTO['id']), str(requestDTO['port']), str(requestDTO['password']), str(requestDTO['key'])
    loadKey = str(requestDTO['key'])
    #deImageId = aes.decrypt(imageId)
    deloadKey = aes.decrypt(loadKey)
    scope, control = str(requestDTO['scope']), str(requestDTO['control'])
    vmName = "vm"+port
    nodePort = str(requestDTO['nodePort'])
    imagePath = str(requestDTO['imagePath'])

    # stream1 = os.popen(createContainerCmd(port, pwd, deImageId))
    # newContainerId = stream1.read()[:12]
    # enContainerId = aes.encrypt(newContainerId)

    # stream2 = os.popen(createImgCmd(newContainerId, userId, port))
    # newImageId = stream2.read()[7:20]
    # enImageId = aes.encrypt(newImageId)

    # os.popen(startContainerCmd(newContainerId))
    # os.popen(copyScriptToContainer(newContainerId))
    # os.popen(stopContainerCmd(newContainerId))

    # Depolyment yaml 파일 생성 
    deploymentPodYaml = generateDeploymentPodYaml(vmName, vmName, deloadKey, port)
    deploymentFilePath = "/home/yaml/"+vmName+"Deployment.yaml"
    with open(deploymentFilePath, 'w') as deploymentYamlFile:
        deploymentYamlFile.write(deploymentPodYaml) 

    # Service yaml 파일 생성 
    servicePodYaml = generateServiceYaml(vmName, port, nodePort)
    serviceFilePath = "/home/yaml/"+vmName+"Service.yaml"
    with open(serviceFilePath, 'w') as serviceYamlFile:
        serviceYamlFile.write(servicePodYaml)
        
    print(deploymentPodYaml)
    print(servicePodYaml)

    os.popen(applyPodCmd(deploymentFilePath))
    os.popen(applyPodCmd(serviceFilePath))

    nodeList = extractNodeInfo()
    time.sleep(60)
    externalNodeIp = extractNodeIpOfPod(nodeList)

    print("nodes: ", nodeList)
    print("externalIp: ", externalNodeIp)

    response = {
            'port': port,
            'externalNodeIp': externalNodeIp
        }


    return jsonify(response), 200



# spring 서버에서 컨테이너 실행 요청이 왔을 때, 컨테이너 실행
@app.route('/start', methods=['POST'])
def start():

    print("hello")
    print(request.get_json())

    requestDTO = request.get_json()
    print("[start requestDTO] ", requestDTO)
    port, containerId = str(requestDTO['port']), str(requestDTO['containerId'])
    #deContainerId = aes.decrypt(containerId)
    pwd = str(requestDTO['password'])
    scope, control = str(requestDTO['scope']), str(requestDTO['control'])

    vmName = "vm"+port

    deploymentFilePath = "/home/yaml/"+vmName+"Deployment.yaml"
    serviceFilePath = "/home/yaml/"+vmName+"Service.yaml"

    os.popen(applyPodCmd(deploymentFilePath))
    os.popen(applyPodCmd(serviceFilePath))

    time.sleep(3)
    
    stream1 = os.popen(getPodName(port))
    podName = stream1.read()[4:-1]
    
    print("podName:", podName)
    
    os.popen(copyScriptToPod(podName, vmName))
    
    time.sleep(1)
    
    changeVncScopeAndControlCmd = "kubectl exec -it "+podName+" bash /tmp/start.sh "+scope+" "+control+" "+pwd+" --kubeconfig /root/kubeconfig.yml"
    os.popen(changeVncScopeAndControlCmd)

    time.sleep(2)

    response = {
            'port' : port,
            'containerId' : containerId
        }

    return jsonify(response), 200



# spring 서버에서 컨테이너 중지 요청이 왔을 때, 컨테이너 중지
@app.route('/stop', methods=['POST'])
def stop():

    requestDTO = request.get_json()
    print("[stop requestDTO] ", requestDTO)
    port, containerId = str(requestDTO['port']), str(requestDTO['containerId'])
    #deContainerId = aes.decrypt(containerId)
    vmName = "vm"+port # containerName과 동일 

    podName = os.popen(getPodName(port)).read()[4:-1]
    namespace = os.popen(getPodNameSpace(podName)).read()[:-1]

    print("start")
    stopScript = createStopScript(vmName)
    scriptFilePath = "/tmp/script/stop/"+vmName+".sh"
    with open(scriptFilePath, 'w') as scriptFile:
        scriptFile.write(stopScript)

    print("stop script: "+stopScript)

    accessContainer = f"kubectl exec -it {podName} bash /tmp/script/stop/{vmName}.sh --kubeconfig /root/kubeconfig.yml"
    os.popen(accessContainer)
    time.sleep(2)

    print("end")

    response = {
            'port' : port,
            'containerId' : containerId
        }

    return jsonify(response), 200



# spring 서버에서 컨테이너 저장 요청이 왔을 때, 현재 컨테이너의 이미지 생성 -> 기존 이미지 삭제 -> push
@app.route('/save', methods=['POST'])
def save() : 

    requestDTO = request.get_json()
    print("[save requestDTO] ", requestDTO)
    userId, port, pwd = str(requestDTO['id']), str(requestDTO['port']), str(requestDTO['pwd'])
    containerId, imageId = str(requestDTO['containerId']), str(requestDTO['imageId'])
    #deContainerId, deImageId = aes.decrypt(containerId), aes.decrypt(imageId)

    # 백업 데이터로 dockerfile 만들고 build하고 registry push 

    vmName = "vm"+port
    imagePath = "registry.p2kcloud.com/base/"+userId
    podName = os.popen(getPodName(port)).read()[4:-1]
    loadKey = aes.encrypt(imagePath+":"+port)
    
    backupScript = createBackupScript(vmName, imagePath, port)
    scriptFilePath = "/tmp/script/backup/"+vmName+".sh"
    with open(scriptFilePath, 'w') as scriptFile:
        scriptFile.write(backupScript)

    print("save script: "+backupScript)

    accessContainer = f"kubectl exec -it {podName} bash /tmp/script/backup/{vmName}.sh --kubeconfig /root/kubeconfig.yml"
    os.popen(accessContainer)
    
    time.sleep(2)

    # stream1 = os.popen(createImgCmd(deContainerId, userId, port))
    # newImageId = stream1.read()[7:20]
    # enImageId = aes.encrypt(newImageId)
    # print("1 : ", stream1.read())

    # stream2 = os.popen(deleteImgCmd(deImageId))
    # print("2 : ", stream2.read())

    # stream3 = os.popen(pushImgCmd(userId, port))
    # print("3 : ", stream3.read())
    # time.sleep(3)


    # print("newImageId : ", newImageId)
    # print("ennewImageId : ", enImageId)
    print("path: "+imagePath+":"+port)

    response = {
            'containerId' : containerId,
            'imageId' : imageId, 
            'loadKey' : loadKey
        }

    return jsonify(response), 200



# spring 서버에서 컨테이너 삭제 요청이 왔을 때, 컨테이너, 이미지 삭제
@app.route('/delete', methods=['POST'])
def delete():

    requestDTO = request.get_json()
    print("[delete requestDTO] ", requestDTO)
    userId, port = str(requestDTO['id']), str(requestDTO['port'])
    containerId, imageId = str(requestDTO['containerId']), str(requestDTO['imageId'])
    #deContainerId, deImageId = aes.decrypt(containerId), aes.decrypt(imageId)

    #os.popen(deleteContainerCmd(deContainerId))
    #os.popen(deleteImgCmd(deImageId))

    vmName = "vm"+port

    deploymentFilePath = "/home/yaml/"+vmName+"Deployment.yaml"
    serviceFilePath = "/home/yaml/"+vmName+"Service.yaml"

    os.popen(deleteYamlFile(deploymentFilePath))
    os.popen(deleteYamlFile(serviceFilePath))


    response = {
            'port' : port,
            'containerId' : containerId
        }

    return jsonify(response), 200

if __name__ == '__main__':

    app.run('0.0.0.0', port=5000, debug=True)