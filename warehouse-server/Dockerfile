FROM nginx:alpine

# Install wget for healthcheck
RUN apk add --no-cache wget

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Create warehouse directory structure with proper permissions
RUN mkdir -p /app/warehouse/uploads/bots && \
    mkdir -p /app/warehouse/uploads/personas && \
    chown -R nginx:nginx /app/warehouse && \
    chmod -R 755 /app/warehouse

# Expose port
EXPOSE 8080

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
