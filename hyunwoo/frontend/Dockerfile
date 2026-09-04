FROM nginx:1.27-alpine

# Copy the web page and frontend assets.
COPY index.html styles.css app.js /usr/share/nginx/html/

# Use the local web server settings.
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
