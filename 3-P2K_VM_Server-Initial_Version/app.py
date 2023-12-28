from flask import Flask, render_template, request, jsonify
import os, time
import base64
import hashlib
from Crypto.Cipher import AES

app = Flask(__name__)

baseImageId = '04a27ba84906' # kasm-1.14.0 이미지 
#baseImageId = '1692c5f95a70e' # 로컬 이미지 

BS = 16
pad = (lambda s: s + (BS - len(s) % BS) * chr(BS - len(s) % BS).encode())
unpad = (lambda s: s[:-ord(s[len(s)-1:])])


# 컨테이너 관련 명령어 
def createContainerCmd(port, pwd, imageId) : # vm+port 이름의 컨테이너 생성 
    return "docker create --shm-size=512m -p "+port+":6901 -e VNC_PW="+pwd+" --name vm"+port+" "+imageId

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
    
    os.popen(startContainerCmd(containerId))
    
    os.popen(copyScriptToContainer(containerId))
    
    time.sleep(1)
    
    #os.popen(changeVncScopeAndControl(containerId, scope, control, pwd))
    changeVncScopeAndControlCmd = "docker exec -it --user root "+containerId+" bash /dockerstartup/start.sh "+scope +" "+control+" "+pwd
    os.popen(changeVncScopeAndControlCmd)

    
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
    scope, control = str(requestDTO['scope']), str(requestDTO['control'])
    deImageId = aes.decrypt(imageId)
    
    stream1 = os.popen(createContainerCmd(port, pwd, deImageId))
    # 해당 이미지 id가 없을 때
    if (stream1.read()[:6] == 'Unable') :
        response = {
            'containerId' : 'null',
            'imageId' : enImageId
        }
        
        return jsonify(response), 404 
    
    newContainerId = stream1.read()[:12]
    enContainerId = aes.encrypt(newContainerId)
    
    stream2 = os.popen(createImgCmd(newContainerId, userId, port))
    newImageId = stream2.read()[7:20]
    enImageId = aes.encrypt(newImageId)
    
    os.popen(startContainerCmd(newContainerId))
    
    os.popen(copyScriptToContainer(newContainerId))
    
    time.sleep(1)
    
    changeVncScopeAndControlCmd = "docker exec -it --user root "+newContainerId+" bash /dockerstartup/start.sh "+scope +" "+control+" "+pwd
    os.popen(changeVncScopeAndControlCmd)

    
    response = {
        'containerId' : enContainerId,
        'imageId' : enImageId
    }
    
    return jsonify(response), 200



# spring 서버에서 컨테이너 실행 요청이 왔을 때, 컨테이너 실행
@app.route('/start', methods=['POST'])
def start():    
    
    requestDTO = request.get_json()
    print("[start requestDTO] ", requestDTO)
    port, containerId = str(requestDTO['port']), str(requestDTO['containerId'])
    deContainerId = aes.decrypt(containerId)
    pwd = str(requestDTO['password'])
    scope, control = str(requestDTO['scope']), str(requestDTO['control'])

    os.popen(startContainerCmd(deContainerId))
    
    time.sleep(1)
    
    #os.popen(changeVncScopeAndControl(deContainerId, scope, control, pwd))
    changeVncScopeAndControlCmd = "docker exec -it --user root "+deContainerId+" bash /dockerstartup/start.sh "+scope +" "+control+" "+pwd
    os.popen(changeVncScopeAndControlCmd)
    
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
    
    os.popen(stopContainerCmd(deContainerId))
    
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
    
    response = {
            'port' : port,
            'containerId' : containerId
        }
    
    return jsonify(response), 200


if __name__ == '__main__':
    app.run('0.0.0.0', port=5000, debug=True)