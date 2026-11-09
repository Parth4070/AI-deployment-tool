# Every preflight check should fail on this project. All values are fake.
FROM node:latest
WORKDIR /app
ENV NODE_ENV=production \
    API_TOKEN=fake-baked-token-value
COPY . .
EXPOSE 8080
