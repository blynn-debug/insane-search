#!/usr/bin/env bash
# valley.town 세션 keepalive 를 AWS 에 배포한다. CloudShell 에서 실행.
#
#   1) 쿠키를 SSM Parameter Store(SecureString)에 저장
#   2) Lambda 함수 생성 (session_keeper.handler)
#   3) EventBridge 로 6시간마다 실행
#   4) (선택) 세션 만료 시 이메일 알림
#
# 사용:
#   session_keeper.py, cookies.txt, deploy_aws.sh 를 CloudShell 에 올린 뒤
#     bash deploy_aws.sh
#   알림까지 받으려면
#     EMAIL=you@example.com bash deploy_aws.sh
#
# 여러 번 실행해도 안전하다(이미 있으면 갱신).
set -euo pipefail

NAME=valley-keepalive
PARAM=/valley/session
ROLE=${NAME}-role
RULE=${NAME}-6h
SCHEDULE="rate(6 hours)"
RUNTIME=python3.12

REGION=$(aws configure get region || echo "${AWS_REGION:-ap-northeast-2}")
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
echo "== 계정 ${ACCOUNT} / 리전 ${REGION}"

# ---------------------------------------------------------------- 1) 쿠키 저장
if [ ! -f cookies.txt ]; then
  echo "!! cookies.txt 가 없다. 로컬에서 만들어 올려라." >&2; exit 1
fi
if ! grep -q '__Secure-nf.session-token' cookies.txt; then
  echo "!! cookies.txt 에 세션 토큰이 없다. 로그인부터 해라." >&2; exit 1
fi
aws ssm put-parameter --name "$PARAM" --type SecureString \
  --value "$(tr -d '\r\n' < cookies.txt)" --overwrite >/dev/null
echo "== 1/4 쿠키를 SSM ${PARAM} 에 저장했다"

# ---------------------------------------------------------------- 2) IAM 역할
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document '{
    "Version":"2012-10-17",
    "Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name "$ROLE" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  echo "== 2/4 IAM 역할 생성. 전파 대기 15초..."
  sleep 15
else
  echo "== 2/4 IAM 역할 재사용"
fi

# 쿠키 파라미터 하나에만 접근. KMS 는 SSM 을 통한 호출로만 제한한다.
aws iam put-role-policy --role-name "$ROLE" --policy-name "${NAME}-ssm" --policy-document "{
  \"Version\":\"2012-10-17\",
  \"Statement\":[
    {\"Effect\":\"Allow\",\"Action\":[\"ssm:GetParameter\",\"ssm:PutParameter\"],
     \"Resource\":\"arn:aws:ssm:${REGION}:${ACCOUNT}:parameter${PARAM}\"},
    {\"Effect\":\"Allow\",\"Action\":[\"kms:Decrypt\",\"kms:Encrypt\"],\"Resource\":\"*\",
     \"Condition\":{\"StringEquals\":{\"kms:ViaService\":\"ssm.${REGION}.amazonaws.com\"}}}
  ]}"

# ---------------------------------------------------------------- 3) Lambda
rm -rf pkg "${NAME}.zip"; mkdir -p pkg
cp session_keeper.py pkg/
(cd pkg && zip -qr "../${NAME}.zip" .)

ENV_VARS="STORE=ssm:${PARAM}"
TOPIC_ARN=""
if [ -n "${EMAIL:-}" ]; then
  TOPIC_ARN=$(aws sns create-topic --name "${NAME}-alert" --query TopicArn --output text)
  aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email --notification-endpoint "$EMAIL" >/dev/null
  aws iam put-role-policy --role-name "$ROLE" --policy-name "${NAME}-sns" --policy-document "{
    \"Version\":\"2012-10-17\",
    \"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sns:Publish\",\"Resource\":\"${TOPIC_ARN}\"}]}"
  ENV_VARS="${ENV_VARS},SNS_TOPIC_ARN=${TOPIC_ARN}"
  echo "== 알림 토픽 생성. ${EMAIL} 로 온 구독 확인 메일을 눌러야 알림이 온다"
fi

if aws lambda get-function --function-name "$NAME" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$NAME" --zip-file "fileb://${NAME}.zip" >/dev/null
  aws lambda wait function-updated --function-name "$NAME"
  aws lambda update-function-configuration --function-name "$NAME" \
    --timeout 30 --environment "Variables={${ENV_VARS}}" >/dev/null
  aws lambda wait function-updated --function-name "$NAME"
  echo "== 3/4 Lambda 갱신"
else
  aws lambda create-function --function-name "$NAME" \
    --runtime "$RUNTIME" --handler session_keeper.handler \
    --role "arn:aws:iam::${ACCOUNT}:role/${ROLE}" \
    --zip-file "fileb://${NAME}.zip" --timeout 30 \
    --environment "Variables={${ENV_VARS}}" >/dev/null
  aws lambda wait function-active --function-name "$NAME"
  echo "== 3/4 Lambda 생성"
fi

# ---------------------------------------------------------------- 4) 스케줄
aws events put-rule --name "$RULE" --schedule-expression "$SCHEDULE" >/dev/null
aws lambda add-permission --function-name "$NAME" --statement-id "${RULE}-invoke" \
  --action lambda:InvokeFunction --principal events.amazonaws.com \
  --source-arn "arn:aws:events:${REGION}:${ACCOUNT}:rule/${RULE}" >/dev/null 2>&1 || true
aws events put-targets --rule "$RULE" \
  --targets "Id=1,Arn=arn:aws:lambda:${REGION}:${ACCOUNT}:function:${NAME}" >/dev/null
echo "== 4/4 EventBridge ${SCHEDULE} 등록"

# ---------------------------------------------------------------- 5) 알람
# 세션 만료는 스크립트가 직접 SNS 로 알린다. 하지만 그 외의 실패
# (권한 오류, 네트워크, EventBridge 정지)는 조용히 멈춘다. 그걸 잡는다.
if [ -n "$TOPIC_ARN" ]; then
  aws cloudwatch put-metric-alarm --alarm-name "${NAME}-errors" \
    --alarm-description "keepalive 실행 실패" \
    --namespace AWS/Lambda --metric-name Errors --statistic Sum \
    --dimensions "Name=FunctionName,Value=${NAME}" \
    --period 21600 --evaluation-periods 1 --threshold 1 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --treat-missing-data notBreaching --alarm-actions "$TOPIC_ARN"

  # 12시간(=2회분) 동안 한 번도 안 돌면 스케줄 자체가 멈춘 것이다.
  # 데이터 없음을 '이상'으로 봐야 잡힌다.
  aws cloudwatch put-metric-alarm --alarm-name "${NAME}-not-running" \
    --alarm-description "keepalive 가 12시간째 실행되지 않음" \
    --namespace AWS/Lambda --metric-name Invocations --statistic Sum \
    --dimensions "Name=FunctionName,Value=${NAME}" \
    --period 43200 --evaluation-periods 1 --threshold 1 \
    --comparison-operator LessThanThreshold \
    --treat-missing-data breaching --alarm-actions "$TOPIC_ARN"
  echo "== 5/5 알람 2개 등록 (실행실패 / 12시간 무실행)"
else
  echo "== 5/5 알람 건너뜀 (EMAIL 미지정)"
fi

# ---------------------------------------------------------------- 확인
echo
echo "== 즉시 1회 실행해서 확인한다"
aws lambda invoke --function-name "$NAME" --cli-binary-format raw-in-base64-out \
  --payload '{}' /tmp/out.json >/tmp/inv.json
# set -e 아래에서 'grep && {...}' 를 쓰면 grep 실패(=정상)일 때 스크립트가 종료된다. if 로 쓴다.
if grep -q FunctionError /tmp/inv.json; then
  echo "!! 실행 실패:"; cat /tmp/out.json; echo
  echo "   로그: aws logs tail /aws/lambda/${NAME} --since 5m"; exit 1
fi
echo "   응답: $(cat /tmp/out.json)"
echo
echo "완료. 앞으로 6시간마다 세션을 갱신한다."
echo "  현재 쿠키 확인 : aws ssm get-parameter --name ${PARAM} --with-decryption --query Parameter.Value --output text"
echo "  로그 보기      : aws logs tail /aws/lambda/${NAME} --since 1h --follow"
echo "  수동 실행      : aws lambda invoke --function-name ${NAME} /tmp/out.json && cat /tmp/out.json"
