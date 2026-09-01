# Enerel's frontend microservice -- plain HTML/CSS/JS, no build step, served
# by nginx. The API is same-origin via the /api/ proxy in nginx.conf.
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html styles.css app.js /usr/share/nginx/html/

EXPOSE 80
