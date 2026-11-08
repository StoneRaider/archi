# Porte de l'oeil : un seul fichier Node, sans dependance.
FROM node:24-alpine
WORKDIR /porte
COPY porte.js .
USER node
EXPOSE 4175
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:4175/sante').then((r)=>process.exit(r.ok?0:1),()=>process.exit(1))"]
CMD ["node", "porte.js"]
