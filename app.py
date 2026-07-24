import os
import json
import logging
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from zefoy_bot import ZefoyBot

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Khởi tạo Flask
app = Flask(__name__)
CORS(app)  # Cho phép CORS

# Đọc config
def load_config():
    config_file = 'config.json'
    if os.path.exists(config_file):
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'cookie_string': '',
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

CONFIG = load_config()

# HTML Template cho trang chủ
INDEX_HTML = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zefoy Bot API</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Courier New', monospace;
            background: #0a0a0a;
            color: #00ff50;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .container {
            max-width: 900px;
            padding: 40px;
            background: #111;
            border-radius: 10px;
            border: 1px solid #00ff50;
            box-shadow: 0 0 30px rgba(0,255,80,0.1);
        }
        h1 {
            color: #00ff50;
            text-align: center;
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 0 0 20px rgba(0,255,80,0.3);
        }
        .subtitle {
            text-align: center;
            color: #00e5ff;
            margin-bottom: 30px;
            font-size: 1.1em;
        }
        .status {
            background: #1a1a1a;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 25px;
            border-left: 3px solid #00ff50;
        }
        .status-item {
            display: flex;
            justify-content: space-between;
            padding: 5px 0;
            color: #aaa;
        }
        .status-item .label { color: #888; }
        .status-item .value { color: #00ff50; }
        .status-item .value.offline { color: #ff2e63; }
        
        .endpoint {
            background: #1a1a1a;
            padding: 15px;
            border-radius: 8px;
            margin: 10px 0;
            border-left: 3px solid #00e5ff;
        }
        .endpoint .method {
            color: #ffaa00;
            font-weight: bold;
        }
        .endpoint .path {
            color: #00e5ff;
        }
        .endpoint .desc {
            color: #aaa;
            margin-top: 5px;
            font-size: 0.9em;
        }
        .code-block {
            background: #0a0a0a;
            padding: 12px;
            border-radius: 5px;
            margin: 8px 0;
            color: #00e5ff;
            font-size: 0.85em;
            overflow-x: auto;
            border: 1px solid #222;
        }
        .footer {
            margin-top: 30px;
            text-align: center;
            color: #555;
            font-size: 0.85em;
            border-top: 1px solid #222;
            padding-top: 20px;
        }
        .badge {
            display: inline-block;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 0.75em;
            font-weight: bold;
        }
        .badge.online {
            background: #00ff50;
            color: #000;
        }
        .badge.offline {
            background: #ff2e63;
            color: #fff;
        }
        .highlight {
            color: #ffaa00;
        }
        @media (max-width: 600px) {
            .container { padding: 20px; margin: 10px; }
            h1 { font-size: 1.8em; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚡ ZEFOY BOT API</h1>
        <div class="subtitle">Tự động tăng tương tác TikTok 🚀</div>
        
        <div class="status">
            <div class="status-item">
                <span class="label">🔐 Status:</span>
                <span class="value {% if status.authenticated %}online{% else %}offline{% endif %}">
                    {{ '🟢 Online' if status.authenticated else '🔴 Offline' }}
                </span>
            </div>
            <div class="status-item">
                <span class="label">📦 Services:</span>
                <span class="value">{{ status.services }}</span>
            </div>
            <div class="status-item">
                <span class="label">🆔 User-Agent:</span>
                <span class="value" style="font-size:0.8em;">{{ status.user_agent }}</span>
            </div>
        </div>
        
        <h2 style="color:#00e5ff; font-size:1.2em; margin-bottom:15px;">📡 API Endpoints</h2>
        
        <div class="endpoint">
            <div><span class="method">GET</span> <span class="path">/</span></div>
            <div class="desc">📄 Trang chủ - Thông tin API</div>
        </div>
        
        <div class="endpoint">
            <div><span class="method">GET</span> <span class="path">/status</span></div>
            <div class="desc">📊 Kiểm tra trạng thái bot</div>
            <div class="code-block">GET /status</div>
        </div>
        
        <div class="endpoint">
            <div><span class="method">POST</span> <span class="path">/services</span></div>
            <div class="desc">📋 Lấy danh sách dịch vụ có sẵn</div>
            <div class="code-block">POST /services</div>
        </div>
        
        <div class="endpoint">
            <div><span class="method">POST</span> <span class="path">/boost</span></div>
            <div class="desc">🚀 Thực hiện tăng tương tác</div>
            <div class="code-block">
                POST /boost<br>
                {<br>
                &nbsp;&nbsp;"video_url": "https://www.tiktok.com/@user/video/123",<br>
                &nbsp;&nbsp;"service": "followers",<br>
                &nbsp;&nbsp;"max_runs": 10<br>
                }
            </div>
        </div>
        
        <div class="footer">
            ⚡ Made with ❤️ | Zefoy Bot API v3.0<br>
            <span style="color:#333;">Bản quyền thuộc về TIENDEV</span>
        </div>
    </div>
</body>
</html>
"""


@app.route('/')
def index():
    """Trang chủ"""
    try:
        bot = ZefoyBot(CONFIG.get('cookie_string', ''), CONFIG.get('user_agent', ''))
        status = bot.get_status()
    except:
        status = {'authenticated': False, 'services': 0, 'user_agent': 'Unknown'}
    
    return render_template_string(INDEX_HTML, status=status)


@app.route('/status', methods=['GET'])
def get_status():
    """Kiểm tra trạng thái bot"""
    try:
        bot = ZefoyBot(CONFIG.get('cookie_string', ''), CONFIG.get('user_agent', ''))
        status = bot.get_status()
        
        # Kiểm tra authenticate
        bot.authenticate()
        status = bot.get_status()
        
        return jsonify({
            'success': True,
            'data': status,
            'message': 'Bot status retrieved successfully'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'data': None,
            'message': f'Error: {str(e)}'
        }), 500


@app.route('/services', methods=['POST'])
def get_services():
    """Lấy danh sách dịch vụ"""
    try:
        cookie = request.json.get('cookie') if request.json else None
        ua = request.json.get('user_agent') if request.json else None
        
        # Sử dụng cookie từ request hoặc từ config
        cookie_string = cookie or CONFIG.get('cookie_string', '')
        user_agent = ua or CONFIG.get('user_agent', '')
        
        if not cookie_string:
            return jsonify({
                'success': False,
                'data': [],
                'message': 'Cookie is required. Please provide cookie in request or config.json'
            }), 400
        
        bot = ZefoyBot(cookie_string, user_agent)
        
        # Authenticate
        if not bot.authenticate():
            return jsonify({
                'success': False,
                'data': [],
                'message': 'Authentication failed. Cookie might be expired.'
            }), 401
        
        # Get services
        services = bot.get_services()
        
        return jsonify({
            'success': True,
            'data': services,
            'message': f'Found {len(services)} services'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'data': [],
            'message': f'Error: {str(e)}'
        }), 500


@app.route('/boost', methods=['POST'])
def boost():
    """Thực hiện tăng tương tác"""
    try:
        data = request.json
        if not data:
            return jsonify({
                'success': False,
                'message': 'Missing request body'
            }), 400
        
        # Validate required fields
        video_url = data.get('video_url')
        if not video_url:
            return jsonify({
                'success': False,
                'message': 'video_url is required'
            }), 400
        
        service_name = data.get('service', 'followers')
        max_runs = data.get('max_runs', 10)
        
        # Validate max_runs
        try:
            max_runs = int(max_runs)
            if max_runs < 1:
                max_runs = 1
            if max_runs > 100:
                max_runs = 100  # Giới hạn an toàn
        except:
            max_runs = 10
        
        # Get cookie từ request hoặc config
        cookie = data.get('cookie') or CONFIG.get('cookie_string', '')
        ua = data.get('user_agent') or CONFIG.get('user_agent', '')
        
        if not cookie:
            return jsonify({
                'success': False,
                'message': 'Cookie is required. Please provide cookie in request or config.json'
            }), 400
        
        # Khởi tạo bot
        bot = ZefoyBot(cookie, ua)
        
        # Thực hiện boost
        result = bot.auto_boost(video_url, service_name, max_runs)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}',
            'runs': 0,
            'errors': [str(e)]
        }), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check cho Render"""
    return jsonify({
        'status': 'healthy',
        'service': 'Zefoy Bot API'
    }), 200


# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'message': 'Endpoint not found'
    }), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'message': 'Internal server error'
    }), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    
    # Load config from environment
    if os.environ.get('COOKIE_STRING'):
        CONFIG['cookie_string'] = os.environ.get('COOKIE_STRING')
    if os.environ.get('USER_AGENT'):
        CONFIG['user_agent'] = os.environ.get('USER_AGENT')
    
    app.run(host='0.0.0.0', port=port, debug=debug)
