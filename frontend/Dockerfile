# Build the static app, then serve it with nginx (which also proxies /api to the backend)
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Cloud builds pass these (public values, not secrets); local builds use dev sign-in
ARG VITE_AUTH_MODE=dev
ARG VITE_ENTRA_CLIENT_ID=
ARG VITE_ENTRA_AUTHORITY=
ENV VITE_API_MODE=http \
    VITE_AUTH_MODE=$VITE_AUTH_MODE \
    VITE_ENTRA_CLIENT_ID=$VITE_ENTRA_CLIENT_ID \
    VITE_ENTRA_AUTHORITY=$VITE_ENTRA_AUTHORITY
RUN npm run build

# Unprivileged nginx: runs as a non-root user and listens on 8080
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
