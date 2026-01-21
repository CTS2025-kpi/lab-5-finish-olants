#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
BUILD_VERSION="$(git rev-parse --short HEAD || echo dev)"
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

aws ecr describe-repositories --repository-names coordinator >/dev/null 2>&1 || aws ecr create-repository --repository-name coordinator >/dev/null
aws ecr describe-repositories --repository-names shard >/dev/null 2>&1 || aws ecr create-repository --repository-name shard >/dev/null

aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin   "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

COORD_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/coordinator:lab5"
SHARD_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/shard:lab5"

docker build --build-arg BUILD_VERSION="$BUILD_VERSION" --build-arg BUILD_TIME="$BUILD_TIME" -t coordinator:lab5 ./coordinator
docker tag coordinator:lab5 "$COORD_URI"
docker push "$COORD_URI"

docker build --build-arg BUILD_VERSION="$BUILD_VERSION" --build-arg BUILD_TIME="$BUILD_TIME" -t shard:lab5 ./shard
docker tag shard:lab5 "$SHARD_URI"
docker push "$SHARD_URI"

echo "Coordinator image: $COORD_URI"
echo "Shard image:       $SHARD_URI"
