# Build the static app, then serve it with nginx (which also proxies /api to the backend)
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Cloud builds pass these (public web config, not secrets); local builds use dev sign-in
ARG VITE_AUTH_MODE=dev
ARG VITE_FIREBASE_API_KEY=
ARG VITE_FIREBASE_AUTH_DOMAIN=
ENV VITE_API_MODE=http VITE_AUTH_MODE=$VITE_AUTH_MODE     VITE_FIREBASE_API_KEY=$VITE_FIREBASE_API_KEY VITE_FIREBASE_AUTH_DOMAIN=$VITE_FIREBASE_AUTH_DOMAIN
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
