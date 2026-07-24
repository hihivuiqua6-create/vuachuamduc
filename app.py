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
CORS(app)

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

# ============================================================
# HTML TEMPLATE - GIAO DIỆN HACKER STYLE
# ============================================================
INDEX_HTML = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🔮 Zefoy Bot - TikTok Tool</title>
    <style>
        /* ===== RESET & BASE ===== */
        * { margin: 0; padding: 0; box-sizing: border-box; }
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&display=swap');
        
        :root {
            --primary: #00ff50;
            --secondary: #00e5ff;
            --danger: #ff2e63;
            --warning: #ffaa00;
            --bg-dark: #0a0a0a;
            --bg-card: #111111;
            --bg-input: #1a1a1a;
            --border-color: #00ff50;
            --text-color: #00ff50;
            --text-muted: #888888;
        }
        
        body {
            font-family: 'Share Tech Mono', monospace;
            background: var(--bg-dark);
            color: var(--text-color);
            min-height: 100vh;
            overflow-x: hidden;
            position: relative;
        }
        
        /* ===== MATRIX RAIN ===== */
        #matrix {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: 0;
            opacity: 0.06;
            pointer-events: none;
        }
        
        /* ===== CONTAINER ===== */
        .container {
            position: relative;
            z-index: 1;
            max-width: 1100px;
            margin: 20px auto;
            padding: 30px;
            background: rgba(10, 10, 10, 0.92);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            box-shadow: 0 0 20px rgba(0,255,80,0.1), inset 0 0 50px rgba(0,255,80,0.03);
            backdrop-filter: blur(10px);
            animation: fadeIn 0.8s ease;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(30px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        /* ===== HEADER ===== */
        .header {
            text-align: center;
            padding-bottom: 25px;
            border-bottom: 1px solid rgba(0,255,80,0.15);
            margin-bottom: 25px;
        }
        .glitch {
            font-family: 'Orbitron', monospace;
            font-size: 3.5em;
            font-weight: 900;
            color: var(--primary);
            text-shadow: 0 0 30px rgba(0,255,80,0.3);
            letter-spacing: 4px;
            position: relative;
            display: inline-block;
        }
        .glitch::before, .glitch::after {
            content: attr(data-text);
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            opacity: 0.7;
        }
        .glitch::before { color: var(--danger); z-index: -1; animation: glitch1 3s infinite; }
        .glitch::after { color: var(--secondary); z-index: -2; animation: glitch2 3s infinite; }
        @keyframes glitch1 {
            0%,100%{transform:translate(0)}
            20%{transform:translate(-2px,2px)}
            40%{transform:translate(2px,-2px)}
            60%{transform:translate(-1px,1px)}
            80%{transform:translate(1px,-1px)}
        }
        @keyframes glitch2 {
            0%,100%{transform:translate(0)}
            20%{transform:translate(2px,-2px)}
            40%{transform:translate(-2px,2px)}
            60%{transform:translate(1px,-1px)}
            80%{transform:translate(-1px,1px)}
        }
        .subtitle {
            font-size: 1.1em;
            color: var(--secondary);
            margin-top: 8px;
            text-shadow: 0 0 20px rgba(0,229,255,0.2);
            letter-spacing: 2px;
        }
        .version {
            font-size: 0.85em;
            color: var(--text-muted);
            margin-top: 5px;
        }
        
        /* ===== STATUS BAR ===== */
        .status-bar {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            padding: 15px 20px;
            background: var(--bg-card);
            border-radius: 8px;
            border: 1px solid rgba(0,255,80,0.1);
            margin-bottom: 25px;
        }
        .status-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 5px 0;
        }
        .status-item .label { color: var(--text-muted); font-size: 0.9em; }
        .status-item .value { color: var(--primary); font-weight: bold; font-size: 1em; }
        .status-item .value.offline { color: var(--danger); }
        .status-item .value.online { color: var(--primary); animation: pulse 1.5s infinite; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
        
        /* ===== TABS ===== */
        .tabs {
            display: flex;
            gap: 5px;
            margin-bottom: 25px;
            border-bottom: 1px solid rgba(0,255,80,0.1);
            padding-bottom: 5px;
        }
        .tab-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            padding: 10px 25px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.95em;
            cursor: pointer;
            transition: all 0.3s ease;
            border-radius: 6px 6px 0 0;
        }
        .tab-btn:hover { color: var(--text-color); background: rgba(0,255,80,0.05); }
        .tab-btn.active {
            color: var(--primary);
            background: rgba(0,255,80,0.08);
        }
        .tab-btn.active::after {
            content: '';
            position: absolute;
            bottom: -6px;
            left: 0;
            width: 100%;
            height: 2px;
            background: var(--primary);
            box-shadow: 0 0 20px rgba(0,255,80,0.5);
        }
        .tab-btn { position: relative; }
        .tab-content { display: none; animation: fadeIn 0.4s ease; }
        .tab-content.active { display: block; }
        
        /* ===== FORM ===== */
        .config-section, .boost-section, .logs-section {
            background: var(--bg-card);
            padding: 25px;
            border-radius: 10px;
            border: 1px solid rgba(0,255,80,0.08);
            margin-bottom: 20px;
        }
        .config-section h3, .boost-section h3, .logs-section h3 {
            color: var(--secondary);
            font-family: 'Orbitron', monospace;
            font-size: 1.1em;
            margin-bottom: 20px;
            text-shadow: 0 0 20px rgba(0,229,255,0.2);
        }
        .form-group { margin-bottom: 18px; }
        .form-group label {
            display: block;
            color: var(--text-color);
            font-weight: bold;
            margin-bottom: 6px;
            font-size: 0.95em;
        }
        .form-group input, .form-group textarea, .form-group select {
            width: 100%;
            padding: 12px 15px;
            background: var(--bg-input);
            border: 1px solid rgba(0,255,80,0.15);
            border-radius: 6px;
            color: var(--text-color);
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.95em;
            transition: all 0.3s ease;
        }
        .form-group input:focus, .form-group textarea:focus, .form-group select:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 20px rgba(0,255,80,0.1);
        }
        .form-group textarea { resize: vertical; min-height: 80px; }
        .form-group select {
            cursor: pointer;
            appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%2300ff50' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 15px center;
        }
        .form-group select option { background: var(--bg-dark); color: var(--text-color); }
        .form-group small {
            display: block;
            color: var(--text-muted);
            font-size: 0.8em;
            margin-top: 4px;
        }
        
        /* ===== BUTTONS ===== */
        .btn-group {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 10px;
        }
        .btn {
            padding: 10px 25px;
            border: none;
            border-radius: 6px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.95em;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 5px 25px rgba(0,0,0,0.4); }
        .btn:active { transform: translateY(0); }
        .btn-primary { background: var(--primary); color: var(--bg-dark); }
        .btn-primary:hover { box-shadow: 0 0 30px rgba(0,255,80,0.3); }
        .btn-secondary { background: var(--secondary); color: var(--bg-dark); }
        .btn-secondary:hover { box-shadow: 0 0 30px rgba(0,229,255,0.3); }
        .btn-success { background: var(--primary); color: var(--bg-dark); }
        .btn-success:hover { box-shadow: 0 0 30px rgba(0,255,80,0.3); }
        .btn-danger { background: var(--danger); color: #fff; }
        .btn-danger:hover { box-shadow: 0 0 30px rgba(255,46,99,0.3); }
        .btn-sm { padding: 6px 15px; font-size: 0.8em; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none !important; }
        
        /* ===== RESULT BOX ===== */
        .result-box {
            margin-top: 15px;
            padding: 15px;
            border-radius: 6px;
            background: rgba(0,0,0,0.3);
            border: 1px solid rgba(0,255,80,0.1);
            min-height: 50px;
            display: none;
        }
        .result-box.show { display: block; animation: fadeIn 0.4s ease; }
        .result-box.success { border-color: var(--primary); color: var(--primary); }
        .result-box.error { border-color: var(--danger); color: var(--danger); }
        .result-box.info { border-color: var(--secondary); color: var(--secondary); }
        
        /* ===== PROGRESS ===== */
        .progress-box {
            margin-top: 15px;
            padding: 15px;
            background: rgba(0,0,0,0.3);
            border-radius: 6px;
            border: 1px solid rgba(0,255,80,0.1);
            display: none;
        }
        .progress-box.show { display: block; }
        .progress-bar {
            width: 100%;
            height: 6px;
            background: rgba(255,255,255,0.05);
            border-radius: 3px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            border-radius: 3px;
            transition: width 0.5s ease;
            width: 0%;
        }
        .progress-text {
            color: var(--text-muted);
            font-size: 0.9em;
            margin-top: 8px;
            text-align: center;
        }
        
        /* ===== STATS ===== */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 15px;
        }
        .stat-card {
            background: rgba(0,0,0,0.3);
            padding: 15px;
            border-radius: 8px;
            text-align: center;
            border: 1px solid rgba(0,255,80,0.05);
        }
        .stat-number {
            font-family: 'Orbitron', monospace;
            font-size: 2em;
            color: var(--secondary);
            font-weight: bold;
        }
        .stat-label { color: var(--text-muted); font-size: 0.8em; margin-top: 4px; }
        
        /* ===== LOGS ===== */
        .logs-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        .logs-actions { display: flex; gap: 8px; }
        .logs-container {
            background: rgba(0,0,0,0.5);
            border-radius: 6px;
            padding: 15px;
            max-height: 400px;
            overflow-y: auto;
            font-size: 0.85em;
            border: 1px solid rgba(0,255,80,0.05);
        }
        .logs-container::-webkit-scrollbar { width: 4px; }
        .logs-container::-webkit-scrollbar-track { background: rgba(0,0,0,0.3); }
        .logs-container::-webkit-scrollbar-thumb { background: var(--primary); border-radius: 2px; }
        .log-entry {
            padding: 4px 0;
            border-bottom: 1px solid rgba(255,255,255,0.02);
            line-height: 1.6;
        }
        .log-entry.system { color: var(--secondary); }
        .log-entry.success { color: var(--primary); }
        .log-entry.error { color: var(--danger); }
        .log-entry.warning { color: var(--warning); }
        .log-entry .time { color: var(--text-muted); margin-right: 10px; }
        
        /* ===== GUIDE ===== */
        .guide { color: var(--text-muted); font-size: 0.9em; line-height: 1.8; }
        .guide ol { padding-left: 20px; margin-bottom: 10px; }
        .guide a { color: var(--secondary); text-decoration: none; }
        .guide a:hover { text-decoration: underline; }
        .code-block {
            background: rgba(0,0,0,0.5);
            padding: 12px;
            border-radius: 4px;
            color: var(--secondary);
            font-size: 0.85em;
            overflow-x: auto;
            border: 1px solid rgba(0,229,255,0.1);
            margin-top: 8px;
        }
        
        /* ===== FOOTER ===== */
        .footer {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid rgba(0,255,80,0.08);
            text-align: center;
            color: var(--text-muted);
            font-size: 0.8em;
            display: flex;
            justify-content: center;
            gap: 15px;
            flex-wrap: wrap;
        }
        .footer strong { color: var(--primary); }
        
        /* ===== RESPONSIVE ===== */
        @media (max-width: 768px) {
            .container { margin: 10px; padding: 15px; }
            .glitch { font-size: 2.2em; }
            .status-bar { grid-template-columns: 1fr; gap: 5px; }
            .tabs { flex-wrap: wrap; }
            .tab-btn { flex: 1; text-align: center; padding: 8px 10px; font-size: 0.8em; }
            .btn-group { flex-direction: column; }
            .btn { width: 100%; text-align: center; }
            .stats-grid { grid-template-columns: repeat(3, 1fr); }
            .stat-number { font-size: 1.5em; }
            .logs-header { flex-direction: column; gap: 10px; }
        }
        @media (max-width: 480px) {
            .glitch { font-size: 1.6em; letter-spacing: 1px; }
            .subtitle { font-size: 0.85em; }
            .config-section, .boost-section, .logs-section { padding: 15px; }
            .stats-grid { grid-template-columns: 1fr 1fr; }
        }
    </style>
</head>
<body>
    <!-- Matrix Rain -->
    <canvas id="matrix"></canvas>
    
    <div class="container">
        <!-- Header -->
        <div class="header">
            <div class="glitch" data-text="ZEFOY BOT">ZEFOY BOT</div>
            <div class="subtitle">⚡ Tự động tăng tương tác TikTok ⚡</div>
            <div class="version">v3.0.3 Premium | Made by TIENDEV</div>
        </div>

        <!-- Status Bar -->
        <div class="status-bar" id="statusBar">
            <div class="status-item">
                <span class="label">🔐 Trạng thái:</span>
                <span class="value offline" id="authStatus">Chưa kết nối</span>
            </div>
            <div class="status-item">
                <span class="label">📦 Dịch vụ:</span>
                <span class="value" id="serviceCount">0</span>
            </div>
            <div class="status-item">
                <span class="label">🔄 Lượt chạy:</span>
                <span class="value" id="runCount">0</span>
            </div>
        </div>

        <!-- Tabs -->
        <div class="tabs">
            <button class="tab-btn active" data-tab="config">⚙️ Cấu hình</button>
            <button class="tab-btn" data-tab="boost">🚀 Boost</button>
            <button class="tab-btn" data-tab="logs">📊 Logs</button>
        </div>

        <!-- Tab Config -->
        <div class="tab-content active" id="tab-config">
            <div class="config-section">
                <h3>🔑 Cookie & User-Agent</h3>
                <div class="form-group">
                    <label for="cookieInput">🍪 Cookie String</label>
                    <textarea id="cookieInput" placeholder="PHPSESSID=xxx; cf_clearance=xxx; ..." rows="4"></textarea>
                    <small>Lấy cookie từ trình duyệt sau khi đăng nhập zefoy.com</small>
                </div>
                <div class="form-group">
                    <label for="uaInput">🖥️ User-Agent</label>
                    <input type="text" id="uaInput" placeholder="Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...">
                    <small>Để trống nếu muốn dùng User-Agent mặc định</small>
                </div>
                <div class="btn-group">
                    <button class="btn btn-primary" onclick="saveConfig()">💾 Lưu cấu hình</button>
                    <button class="btn btn-secondary" onclick="testConnection()">🔌 Kiểm tra kết nối</button>
                    <button class="btn btn-danger" onclick="clearConfig()">🗑️ Xóa cấu hình</button>
                </div>
                <div id="configResult" class="result-box"></div>
            </div>
            <div class="config-section">
                <h3>📋 Hướng dẫn lấy Cookie</h3>
                <div class="guide">
                    <ol>
                        <li>Đăng nhập vào <a href="https://zefoy.com" target="_blank">zefoy.com</a></li>
                        <li>Mở DevTools (F12) → Tab Application → Cookies</li>
                        <li>Sao chép toàn bộ cookie string hoặc từng cookie</li>
                        <li>Dán vào ô Cookie String bên trên</li>
                    </ol>
                    <div class="code-block">
                        // Ví dụ cookie string<br>
                        PHPSESSID=fnknouvnnct8a9skvckni5g16q; cf_clearance=7tEaC9md...; zf=83f4a8...
                    </div>
                </div>
            </div>
        </div>

        <!-- Tab Boost -->
        <div class="tab-content" id="tab-boost">
            <div class="boost-section">
                <h3>🚀 Thực hiện Boost</h3>
                <div class="form-group">
                    <label for="videoUrl">📹 Link TikTok</label>
                    <input type="text" id="videoUrl" placeholder="https://www.tiktok.com/@username/video/123456789">
                    <small>Link video hoặc profile TikTok</small>
                </div>
                <div class="form-group">
                    <label for="serviceSelect">🎯 Dịch vụ</label>
                    <select id="serviceSelect">
                        <option value="followers">👥 Followers</option>
                        <option value="hearts">❤️ Hearts (Likes)</option>
                        <option value="views">👁️ Views</option>
                        <option value="comments">💬 Comments</option>
                        <option value="shares">🔄 Shares</option>
                    </select>
                    <small>Chọn dịch vụ muốn tăng</small>
                </div>
                <div class="form-group">
                    <label for="maxRuns">🔢 Số lượt chạy</label>
                    <input type="number" id="maxRuns" value="10" min="1" max="100">
                    <small>Mỗi lượt sẽ tăng tương tác, tối đa 100</small>
                </div>
                <div class="btn-group">
                    <button class="btn btn-success" onclick="startBoost()">▶️ Bắt đầu Boost</button>
                    <button class="btn btn-danger" onclick="stopBoost()">⏹️ Dừng lại</button>
                </div>
                <div id="boostResult" class="result-box"></div>
                <div class="progress-box" id="boostProgress">
                    <div class="progress-bar">
                        <div class="progress-fill" id="progressFill" style="width: 0%"></div>
                    </div>
                    <div class="progress-text" id="progressText">Đang xử lý...</div>
                </div>
            </div>
            <div class="config-section">
                <h3>📊 Thống kê nhanh</h3>
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-number" id="totalRuns">0</div>
                        <div class="stat-label">Tổng lượt chạy</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number" id="successRuns">0</div>
                        <div class="stat-label">Thành công</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number" id="failRuns">0</div>
                        <div class="stat-label">Thất bại</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Tab Logs -->
        <div class="tab-content" id="tab-logs">
            <div class="logs-section">
                <div class="logs-header">
                    <h3>📊 Logs System</h3>
                    <div class="logs-actions">
                        <button class="btn btn-sm btn-secondary" onclick="clearLogs()">🗑️ Clear</button>
                        <button class="btn btn-sm btn-primary" onclick="exportLogs()">📥 Export</button>
                    </div>
                </div>
                <div class="logs-container" id="logsContainer">
                    <div class="log-entry system"><span class="time">[SYSTEM]</span> 🔮 Zefoy Bot v3.0.3 đã sẵn sàng</div>
                    <div class="log-entry system"><span class="time">[SYSTEM]</span> 👋 Chào mừng bạn đến với tool TikTok</div>
                </div>
            </div>
        </div>

        <!-- Footer -->
        <div class="footer">
            <span>🔒 Bản quyền thuộc về <strong>TIENDEV</strong></span>
            <span>|</span>
            <span>⚡ Tool siêu VIP Pro</span>
            <span>|</span>
            <span>💀 Hacker Style</span>
        </div>
    </div>

    <script>
        // ===== MATRIX RAIN =====
        (function() {
            const canvas = document.getElementById('matrix');
            const ctx = canvas.getContext('2d');
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
            const chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';
            const fontSize = 14;
            const columns = Math.floor(canvas.width / fontSize);
            const drops = Array(columns).fill(1);
            function draw() {
                ctx.fillStyle = 'rgba(0,0,0,0.05)';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.fillStyle = '#00ff50';
                ctx.font = fontSize + 'px monospace';
                for (let i = 0; i < drops.length; i++) {
                    const char = chars[Math.floor(Math.random() * chars.length)];
                    ctx.fillText(char, i * fontSize, drops[i] * fontSize);
                    if (drops[i] * fontSize > canvas.height && Math.random() > 0.975) drops[i] = 0;
                    drops[i]++;
                }
            }
            setInterval(draw, 60);
            window.addEventListener('resize', () => {
                canvas.width = window.innerWidth;
                canvas.height = window.innerHeight;
            });
        })();

        // ===== STATE =====
        const state = { isRunning: false, totalRuns: 0, successRuns: 0, failRuns: 0, logs: [] };
        const $ = id => document.getElementById(id);
        const cookieInput = $('cookieInput');
        const uaInput = $('uaInput');
        const videoUrl = $('videoUrl');
        const serviceSelect = $('serviceSelect');
        const maxRuns = $('maxRuns');
        const authStatus = $('authStatus');
        const serviceCount = $('serviceCount');
        const runCount = $('runCount');
        const logsContainer = $('logsContainer');
        const configResult = $('configResult');
        const boostResult = $('boostResult');
        const boostProgress = $('boostProgress');
        const progressFill = $('progressFill');
        const progressText = $('progressText');
        const totalRuns = $('totalRuns');
        const successRuns = $('successRuns');
        const failRuns = $('failRuns');

        // ===== TABS =====
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                this.classList.add('active');
                document.getElementById('tab-' + this.dataset.tab).classList.add('active');
            });
        });

        // ===== LOGS =====
        function addLog(message, type = 'system') {
            const time = new Date().toLocaleTimeString();
            const entry = document.createElement('div');
            entry.className = 'log-entry ' + type;
            entry.innerHTML = '<span class="time">[' + time + ']</span> ' + message;
            logsContainer.appendChild(entry);
            logsContainer.scrollTop = logsContainer.scrollHeight;
            state.logs.push({ time, message, type });
        }
        function clearLogs() {
            logsContainer.innerHTML = '';
            state.logs = [];
            addLog('🗑️ Logs đã được xóa', 'system');
        }
        function exportLogs() {
            const text = state.logs.map(l => '[' + l.time + '] ' + l.message).join('\\n');
            const blob = new Blob([text], { type: 'text/plain' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'zefoy-logs-' + Date.now() + '.txt';
            a.click();
            URL.revokeObjectURL(url);
            addLog('📥 Đã export logs', 'system');
        }

        function showResult(el, msg, type = 'info') {
            el.textContent = msg;
            el.className = 'result-box show ' + type;
        }
        function hideResult(el) { el.className = 'result-box'; el.textContent = ''; }

        function updateStatus(authenticated, services = 0) {
            if (authenticated) {
                authStatus.textContent = '🟢 Đã kết nối';
                authStatus.className = 'value online';
            } else {
                authStatus.textContent = '🔴 Chưa kết nối';
                authStatus.className = 'value offline';
            }
            serviceCount.textContent = services;
        }
        function updateStats() {
            totalRuns.textContent = state.totalRuns;
            successRuns.textContent = state.successRuns;
            failRuns.textContent = state.failRuns;
            runCount.textContent = state.totalRuns;
        }

        // ===== API CALLS =====
        async function saveConfig() {
            const cookie = cookieInput.value.trim();
            const ua = uaInput.value.trim();
            if (!cookie) { showResult(configResult, '⚠️ Vui lòng nhập Cookie String!', 'error'); return; }
            showResult(configResult, '⏳ Đang lưu cấu hình...', 'info');
            try {
                const res = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cookie_string: cookie, user_agent: ua })
                });
                const data = await res.json();
                if (data.success) {
                    showResult(configResult, '✅ Lưu cấu hình thành công!', 'success');
                    addLog('✅ Đã lưu cấu hình mới', 'success');
                    await testConnection();
                } else {
                    showResult(configResult, '❌ ' + data.message, 'error');
                    addLog('❌ Lỗi lưu config: ' + data.message, 'error');
                }
            } catch (e) {
                showResult(configResult, '❌ Lỗi kết nối: ' + e.message, 'error');
                addLog('❌ Lỗi kết nối: ' + e.message, 'error');
            }
        }

        async function testConnection() {
            const cookie = cookieInput.value.trim();
            const ua = uaInput.value.trim();
            if (!cookie) { showResult(configResult, '⚠️ Vui lòng nhập Cookie String trước!', 'error'); return; }
            showResult(configResult, '⏳ Đang kiểm tra kết nối...', 'info');
            try {
                const res = await fetch('/api/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cookie_string: cookie, user_agent: ua })
                });
                const data = await res.json();
                if (data.success) {
                    updateStatus(true, data.services || 0);
                    showResult(configResult, '✅ Kết nối thành công! Tìm thấy ' + (data.services || 0) + ' dịch vụ.', 'success');
                    addLog('✅ Kết nối thành công, ' + (data.services || 0) + ' dịch vụ', 'success');
                } else {
                    updateStatus(false);
                    showResult(configResult, '❌ ' + data.message, 'error');
                    addLog('❌ Kết nối thất bại: ' + data.message, 'error');
                }
            } catch (e) {
                updateStatus(false);
                showResult(configResult, '❌ Lỗi kết nối: ' + e.message, 'error');
                addLog('❌ Lỗi kết nối: ' + e.message, 'error');
            }
        }

        function clearConfig() {
            if (!confirm('Bạn có chắc muốn xóa cấu hình?')) return;
            cookieInput.value = '';
            uaInput.value = '';
            hideResult(configResult);
            updateStatus(false);
            addLog('🗑️ Đã xóa cấu hình', 'system');
        }

        async function startBoost() {
            if (state.isRunning) { addLog('⚠️ Bot đang chạy, vui lòng đợi!', 'warning'); return; }
            const url = videoUrl.value.trim();
            if (!url) { showResult(boostResult, '⚠️ Vui lòng nhập link TikTok!', 'error'); return; }
            const service = serviceSelect.value;
            const runs = parseInt(maxRuns.value) || 10;
            
            state.isRunning = true;
            boostProgress.classList.add('show');
            progressFill.style.width = '0%';
            progressText.textContent = 'Đang bắt đầu...';
            hideResult(boostResult);
            addLog('🚀 Bắt đầu boost: ' + service + ' - ' + runs + ' lượt', 'system');

            try {
                const cookie = cookieInput.value.trim();
                if (!cookie) {
                    showResult(boostResult, '⚠️ Vui lòng cấu hình Cookie trước!', 'error');
                    state.isRunning = false;
                    return;
                }
                const res = await fetch('/api/boost', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        video_url: url,
                        service: service,
                        max_runs: runs,
                        cookie_string: cookie,
                        user_agent: uaInput.value.trim()
                    })
                });
                const data = await res.json();
                if (data.success) {
                    state.totalRuns += data.runs || 0;
                    state.successRuns += data.runs || 0;
                    showResult(boostResult, '✅ ' + (data.message || 'Boost thành công!') + ' (' + (data.runs || 0) + ' lượt)', 'success');
                    addLog('✅ Boost thành công: ' + (data.runs || 0) + ' lượt', 'success');
                } else {
                    state.failRuns += 1;
                    showResult(boostResult, '❌ ' + (data.message || 'Lỗi không xác định'), 'error');
                    addLog('❌ Boost thất bại: ' + (data.message || 'Lỗi không xác định'), 'error');
                }
            } catch (e) {
                state.failRuns += 1;
                showResult(boostResult, '❌ Lỗi: ' + e.message, 'error');
                addLog('❌ Lỗi boost: ' + e.message, 'error');
            }
            
            progressFill.style.width = '100%';
            progressText.textContent = 'Hoàn tất!';
            setTimeout(() => {
                boostProgress.classList.remove('show');
                progressFill.style.width = '0%';
            }, 2000);
            state.isRunning = false;
            updateStats();
        }

        function stopBoost() {
            if (!state.isRunning) { addLog('⚠️ Bot không đang chạy', 'warning'); return; }
            state.isRunning = false;
            addLog('⏹️ Đã dừng boost theo yêu cầu', 'warning');
            showResult(boostResult, '⏹️ Đã dừng boost', 'info');
        }

        // Load config mặc định
        window.onload = function() {
            fetch('/api/config')
                .then(res => res.json())
                .then(data => {
                    if (data.cookie_string) {
                        cookieInput.value = data.cookie_string;
                        addLog('📂 Đã tải cấu hình từ server', 'system');
                    }
                    if (data.user_agent) uaInput.value = data.user_agent;
                    if (data.cookie_string) testConnection();
                })
                .catch(() => {});
        };
    </script>
</body>
</html>
"""

# ============================================================
# ROUTES
# ============================================================

@app.route('/')
def index():
    """Trang chủ - Giao diện Web"""
    return render_template_string(INDEX_HTML)


@app.route('/api/config', methods=['GET'])
def get_config():
    """Lấy cấu hình hiện tại"""
    return jsonify({
        'cookie_string': CONFIG.get('cookie_string', ''),
        'user_agent': CONFIG.get('user_agent', '')
    })


@app.route('/api/config', methods=['POST'])
def save_config_api():
    """Lưu cấu hình"""
    try:
        data = request.json
        cookie = data.get('cookie_string', '').strip()
        ua = data.get('user_agent', '').strip()
        
        if not cookie:
            return jsonify({'success': False, 'message': 'Cookie không được để trống'}), 400
        
        CONFIG['cookie_string'] = cookie
        if ua:
            CONFIG['user_agent'] = ua
        
        # Lưu vào file
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(CONFIG, f, indent=4, ensure_ascii=False)
        
        return jsonify({'success': True, 'message': 'Đã lưu cấu hình thành công'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/test', methods=['POST'])
def test_connection_api():
    """Kiểm tra kết nối với Zefoy"""
    try:
        data = request.json
        cookie = data.get('cookie_string', '').strip()
        ua = data.get('user_agent', '').strip()
        
        if not cookie:
            return jsonify({'success': False, 'message': 'Cookie không được để trống'}), 400
        
        bot = ZefoyBot(cookie, ua or CONFIG.get('user_agent', ''))
        
        if bot.authenticate():
            services = bot.get_services()
            return jsonify({
                'success': True,
                'services': len(services),
                'message': 'Kết nối thành công'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Cookie hết hạn hoặc không hợp lệ. Vui lòng cập nhật cookie mới.'
            }), 401
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/boost', methods=['POST'])
def boost_api():
    """Thực hiện boost"""
    try:
        data = request.json
        video_url = data.get('video_url', '').strip()
        service = data.get('service', 'followers')
        max_runs = int(data.get('max_runs', 10))
        cookie = data.get('cookie_string', '').strip()
        ua = data.get('user_agent', '').strip()
        
        if not video_url:
            return jsonify({'success': False, 'message': 'video_url không được để trống'}), 400
        
        if not cookie:
            return jsonify({'success': False, 'message': 'Cookie không được để trống'}), 400
        
        bot = ZefoyBot(cookie, ua or CONFIG.get('user_agent', ''))
        result = bot.auto_boost(video_url, service, max_runs)
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e), 'runs': 0, 'errors': [str(e)]}), 500


@app.route('/api/services', methods=['POST'])
def services_api():
    """Lấy danh sách dịch vụ"""
    try:
        data = request.json or {}
        cookie = data.get('cookie_string', '').strip()
        ua = data.get('user_agent', '').strip()
        
        if not cookie:
            cookie = CONFIG.get('cookie_string', '')
        
        if not cookie:
            return jsonify({'success': False, 'message': 'Cookie không được để trống'}), 400
        
        bot = ZefoyBot(cookie, ua or CONFIG.get('user_agent', ''))
        
        if not bot.authenticate():
            return jsonify({'success': False, 'message': 'Cookie hết hạn hoặc không hợp lệ'}), 401
        
        services = bot.get_services()
        return jsonify({
            'success': True,
            'data': services,
            'message': f'Found {len(services)} services'
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/health')
def health_check():
    """Health check cho Render"""
    return jsonify({'status': 'healthy', 'service': 'Zefoy Bot API'})


# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    
    # Load từ biến môi trường
    if os.environ.get('COOKIE_STRING'):
        CONFIG['cookie_string'] = os.environ.get('COOKIE_STRING')
    if os.environ.get('USER_AGENT'):
        CONFIG['user_agent'] = os.environ.get('USER_AGENT')
    
    app.run(host='0.0.0.0', port=port, debug=debug)
