# kakao-stmp-server
카테캠 3단계 smtp 전송을 위한 서버 구축

[Related Repository](https://github.com/Step3-kakao-tech-campus/Team3_BE)

- Naver Cloud의 서버를 구축하여 Flask를 실행합니다. 

#### Flask 사용 이유 

크램폴린 환경에서는 카카오 정책으로 인해 HTTP 통신만 가능하다는 프로토콜 통신 제한이 있어, 외부에 SMTP 서버를 구축하여 SMTP 이메일 전송을 구현하기로 하였습니다. POST 요청에 의한 이메일 발송만 구현하면 되었기에 간결하면서도 필요한 기능을 구현할 수 있는 도구를 선택하려고 하였고, 이에 간결하게 사용할 수 있는 웹 Framework인 Flask로 메일 전송 요청에 따른 메일 전송 기능을 구현하게 되었습니다.

#### SMTP 서버 구조 설명 

크램폴린 환경에서만 Naver Cloud 환경에서의 flask 서버를 활용합니다.

**HTTP POST 요청 생성하기**

- SpringBoot 상에서 Flask로 보내게 될 HTTP 요청에 대한 request를 생성하기 위해 MultiValueMap을 이용하여 request body를 생성합니다.
- HTTP Header와 requestURL을 설정하고, Proxy 설정이 된 RestTemplate을 이용하여 HTTP 통신을 통해 Flask 서버로 POST 요청을 전송합니다.

**SMTP 요청 생성하기**

- HTTP POST 요청이 들어오면, Flask 서버는 SMTP 서버로 보내게 될 SMTP 요청을 생성합니다.
- request body에서 필요한 정보를 추출하고, SMTP 요청을 생성합니다. 이때, SMTP의 text 부분에 들어갈 내용이 html이므로, MIME Type을 text/html으로 설정해야 요청이 정상적으로 보내집니다.
- SMTP 권한 설정한 후, 발신자와 수신자 그리고 text를 설정하여 SMTP 서버로 요청을 보냅니다.
- 요청이 성공적으로 전송되면 200을 반환합니다.

### Flask SMTP 서버 실행 

1. 프로젝트 클론 

```
$ git clone https://github.com/sososo0/kakao-stmp-server.git
```

2. start.sh 권한 주기 

```
$ chmod +x start.sh
```

3. Flask SMTP 서버 실행 

```
$ ./start.sh
```