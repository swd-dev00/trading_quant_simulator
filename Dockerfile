FROM node:20.11.1-alpine3.19

WORKDIR /app

COPY index.js package.json ./

EXPOSE 8080

CMD ["node", "index.js"]
