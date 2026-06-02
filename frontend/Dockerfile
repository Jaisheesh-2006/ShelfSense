# Build the React dashboard, then serve the static bundle with nginx. Build context = ./frontend.

# ---- Stage 1: build the static bundle ----
FROM node:20-alpine AS build
WORKDIR /app
# Install deps first (better layer caching). npm ci when a lockfile is present, else npm install.
COPY package.json package-lock.json* ./
RUN npm ci || npm install
COPY . .
RUN npm run build

# ---- Stage 2: serve with nginx ----
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=6 \
    CMD wget -qO- http://localhost/ >/dev/null 2>&1 || exit 1
