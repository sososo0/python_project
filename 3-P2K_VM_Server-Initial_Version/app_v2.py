from flask import Flask, render_template, request, jsonify
import os, time
import base64
import hashlib
import yaml
from Crypto.Cipher import AES

app = Flask(__name__)

baseImageId = 'a1f78e91446e' # kasm-1.14.0 이미지
#baseImageId = '1692c5f95a70e' # 로컬 이미지

BS = 16
pad = (lambda s: s + (BS - len(s) % BS) * chr(BS - len(s) % BS).encode())
unpad = (lambda s: s[:-ord(s[len(s)-1:])])

# deployment pod 만드는 함수
def generateDeploymentPodYaml(deploymentName, containerName, imageName, scriptPath, scope, control, pwd) : 
    deploymentDefinition = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": deploymentName}, 
        "spec": {
            "replicas": 1,
            "selector": {
                "matchLabels": {
                    "app": "webdesktop" # service에서 pod를 선택할 때 구별하는 용도 
                }
            },
            "template": {
                "metadata": {
                    "labels": {
                        "app": "webdesktop" # 새로운 pod가 생성될 때 template 정의 
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
            "selector": {"app": "webdesktop"},
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

# Pod yaml로 생성하기 
def applyPodCmd(yamlFilePath):
    return "kubectl apply -f " + yamlFilePath + " --kubeconfig /root/kubeconfig.yml"

# deployment Pod 지우기  
def deleteDeployPodCmd(deploymentName): 
    return "kubectl delete deployment " + deploymentName + " --kubeconfig /root/kubeconfig.yml"

# service Pod 지우기  
def deleteServicePodCmd(serviceName): 
    return "kubectl delete service " + serviceName + " --kubeconfig /root/kubeconfig.yml"

# yaml 파일 지우기 
def deleteYamlFile(yamlFilePath):
    return "rm /home/yaml/ " + yamlFilePath

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
    deploymentPodYaml = generateDeploymentPodYaml(vmName, vmName, imagePath, scriptPath, scope, control, pwd)
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

    response = {
            'port': port,
            'containerId' : enContainerId,
            'imageId' : enImageId
        }

    return jsonify(response), 200



#spring 서버에서 가상환경 로드했을 때, 이미지로 컨테이너 생성 후 새로운 이미지로 저장
@app.route('/load', methods=['POST'])
def load() :

    requestDTO = request.get_json()
    print("[load requestDTO] ", requestDTO)
    userId, port, pwd, imageId = str(requestDTO['id']), str(requestDTO['port']), str(requestDTO['password']), str(requestDTO['key'])
    deImageId = aes.decrypt(imageId)

    stream1 = os.popen(createContainerCmd(port, pwd, deImageId))
    newContainerId = stream1.read()[:12]
    enContainerId = aes.encrypt(newContainerId)

    stream2 = os.popen(createImgCmd(newContainerId, userId, port))
    newImageId = stream2.read()[7:20]
    enImageId = aes.encrypt(newImageId)

    scope, control = str(requestDTO['scope']), str(requestDTO['control'])
    vmName = "vm"+port
    scriptPath = "/dockerstartup/start.sh"
    nodePort = str(requestDTO['nodePort'])
    imagePath = str(requestDTO['imagePath'])

    os.popen(startContainerCmd(newContainerId))
    os.popen(copyScriptToContainer(newContainerId))
    os.popen(stopContainerCmd(newContainerId))

    # Depolyment yaml 파일 생성 
    deploymentPodYaml = generateDeploymentPodYaml(vmName, vmName, imagePath, scriptPath, scope, control, pwd)
    deploymentFilePath = "/home/yaml/"+vmName+"Deployment.yaml"
    with open(deploymentFilePath, 'w') as deploymentYamlFile:
        deploymentYamlFile.write(deploymentPodYaml) 

    # Service yaml 파일 생성 
    servicePodYaml = generateServiceYaml(vmName, port, nodePort)
    serviceFilePath = "/home/yaml/"+vmName+"Service.yaml"
    with open(serviceFilePath, 'w') as serviceYamlFile:
        serviceYamlFile.write(servicePodYaml)

    response = {
        'containerId' : enContainerId,
        'imageId' : enImageId
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
    deContainerId = aes.decrypt(containerId)
    pwd = str(requestDTO['password'])
    scope, control = str(requestDTO['scope']), str(requestDTO['control'])

    vmName = "vm"+port

    deploymentFilePath = "/home/yaml/"+vmName+"Deployment.yaml"
    serviceFilePath = "/home/yaml/"+vmName+"Service.yaml"

    print(applyPodCmd(deploymentFilePath))
    print(applyPodCmd(serviceFilePath))

    os.popen(applyPodCmd(deploymentFilePath))
    os.popen(applyPodCmd(serviceFilePath))

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
    deContainerId = aes.decrypt(containerId)
    vmName = "vm"+port

    print(deleteDeployPodCmd(vmName))
    print(deleteServicePodCmd(vmName))

    os.popen(deleteDeployPodCmd(vmName))
    os.popen(deleteServicePodCmd(vmName))

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
    deContainerId, deImageId = aes.decrypt(containerId), aes.decrypt(imageId)

    stream1 = os.popen(createImgCmd(deContainerId, userId, port))
    newImageId = stream1.read()[7:20]
    enImageId = aes.encrypt(newImageId)
    print("1 : ", stream1.read())

    stream2 = os.popen(deleteImgCmd(deImageId))
    print("2 : ", stream2.read())

    stream3 = os.popen(pushImgCmd(userId, port))
    print("3 : ", stream3.read())
    time.sleep(3)

    print("newImageId : ", newImageId)
    print("ennewImageId : ", enImageId)

    response = {
            'containerId' : containerId,
            'imageId' : enImageId
        }

    return jsonify(response), 200



# spring 서버에서 컨테이너 삭제 요청이 왔을 때, 컨테이너, 이미지 삭제
@app.route('/delete', methods=['POST'])
def delete():

    requestDTO = request.get_json()
    print("[delete requestDTO] ", requestDTO)
    userId, port = str(requestDTO['id']), str(requestDTO['port'])
    containerId, imageId = str(requestDTO['containerId']), str(requestDTO['imageId'])
    deContainerId, deImageId = aes.decrypt(containerId), aes.decrypt(imageId)

    os.popen(deleteContainerCmd(deContainerId))
    os.popen(deleteImgCmd(deImageId))

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