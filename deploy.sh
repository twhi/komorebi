#!/bin/bash
ACCOUNT_ID="709039349524" 
REGION="eu-west-2"
IMAGE_NAME="komorebi-app"
SERVICE_NAME="komorebi-app"
REPO_URL="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$IMAGE_NAME"

echo "--- 🔐 Logging into ECR ---"
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $REPO_URL

echo "--- 🏗️ Building and Tagging ---"
docker build -t $IMAGE_NAME .
docker tag $IMAGE_NAME:latest $REPO_URL:latest

echo "--- 🚀 Pushing to ECR ---"
docker push $REPO_URL:latest

echo "--- 🔄 Refreshing ECS Service ---"
aws ecs express deploy --name $SERVICE_NAME --image $REPO_URL:latest --update

echo "--- ✅ Deployment Started! ---"