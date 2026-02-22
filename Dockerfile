FROM node:20-alpine

WORKDIR /app

COPY --chown=node:node index.js package.json ./
RUN npm install --production

USER node

EXPOSE 8080

CMD ["node", "index.js"]
