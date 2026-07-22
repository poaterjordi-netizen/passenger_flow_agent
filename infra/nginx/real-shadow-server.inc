# Include this file only inside metro.9m-zx.com's TLS server block.
location = /real-shadow {
    auth_basic "Metro real-shadow";
    auth_basic_user_file /etc/nginx/metro-real-shadow.htpasswd;
    return 308 /real-shadow/;
}

location = /real-shadow/health {
    auth_basic "Metro real-shadow";
    auth_basic_user_file /etc/nginx/metro-real-shadow.htpasswd;
    limit_except GET { deny all; }
    limit_req zone=metro_real_shadow_api burst=5 nodelay;
    limit_conn metro_real_shadow_conn 4;
    proxy_pass http://127.0.0.1:18080/health;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 3s;
    proxy_read_timeout 10s;
    proxy_intercept_errors on;
    error_page 502 503 504 = @metro_real_shadow_offline;
}

location ~ ^/real-shadow/api/v1/assistant/sessions/[A-Za-z0-9_-]+/messages$ {
    auth_basic "Metro real-shadow";
    auth_basic_user_file /etc/nginx/metro-real-shadow.htpasswd;
    limit_except POST { deny all; }
    limit_req zone=metro_real_shadow_assistant burst=2 nodelay;
    limit_conn metro_real_shadow_assistant_conn 1;
    client_max_body_size 8k;
    rewrite ^/real-shadow(/.*)$ $1 break;
    proxy_pass http://127.0.0.1:18080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_connect_timeout 3s;
    proxy_send_timeout 15s;
    proxy_read_timeout 190s;
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
    proxy_intercept_errors on;
    error_page 502 503 504 = @metro_real_shadow_offline;
}

location /real-shadow/api/ {
    auth_basic "Metro real-shadow";
    auth_basic_user_file /etc/nginx/metro-real-shadow.htpasswd;
    limit_except GET POST { deny all; }
    limit_req zone=metro_real_shadow_api burst=20 nodelay;
    limit_conn metro_real_shadow_conn 8;
    client_max_body_size 16k;
    proxy_pass http://127.0.0.1:18080/api/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_connect_timeout 3s;
    proxy_send_timeout 15s;
    proxy_read_timeout 190s;
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
    proxy_intercept_errors on;
    error_page 502 503 504 = @metro_real_shadow_offline;
}

location /real-shadow/ {
    auth_basic "Metro real-shadow";
    auth_basic_user_file /etc/nginx/metro-real-shadow.htpasswd;
    limit_except GET { deny all; }
    # Preserve the base path expected by the production Vite preview. Stripping
    # it here makes Vite redirect back to /real-shadow/ forever.
    proxy_pass http://127.0.0.1:18080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection "";
    proxy_connect_timeout 3s;
    proxy_read_timeout 30s;
    proxy_intercept_errors on;
    error_page 502 503 504 = @metro_real_shadow_offline;
}

location @metro_real_shadow_offline {
    internal;
    auth_basic off;
    default_type text/html;
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
    return 503 '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>真实数据体验暂时离线</title><style>body{margin:0;background:#07111f;color:#dbeafe;font:16px system-ui;display:grid;min-height:100vh;place-items:center}.card{max-width:560px;margin:24px;padding:32px;border:1px solid #334155;border-radius:18px;background:#0f1d2e}h1{font-size:24px}p{color:#94a3b8;line-height:1.7}a{color:#67e8f9}</style><div class="card"><h1>真实数据体验暂时离线</h1><p>本机受治理服务、网络或加密隧道当前不可达。本页不会改用猜测结果；合成数据体验站仍可正常展示。</p><a href="/">返回合成数据体验站</a></div></html>';
}
