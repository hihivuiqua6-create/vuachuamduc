import os
import re
import sys
import time
import json
import base64
import urllib.parse
import logging
from typing import Dict, List, Optional, Tuple

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Please install: pip install requests beautifulsoup4")
    sys.exit(1)

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ZefoyBot:
    """Zefoy Bot API - Tự động tăng tương tác TikTok"""
    
    def __init__(self, cookie_string: str, user_agent: str = None):
        """
        Khởi tạo bot với cookie và user-agent
        
        Args:
            cookie_string: Cookie từ trình duyệt
            user_agent: User-Agent (optional)
        """
        self.cookie_string = cookie_string
        self.user_agent = user_agent or self._get_default_ua()
        self.session = self._setup_session()
        self.services = []
        self.is_authenticated = False
        
    def _get_default_ua(self) -> str:
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    def _setup_session(self) -> requests.Session:
        """Thiết lập session với cookie và headers"""
        session = requests.Session()
        
        # Parse cookie string
        cookies = {}
        for item in self.cookie_string.split(';'):
            item = item.strip()
            if '=' in item:
                k, v = item.split('=', 1)
                cookies[k.strip()] = v.strip()
        
        session.cookies.update(cookies)
        
        # Headers mặc định
        session.headers.update({
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'none',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': self.user_agent,
        })
        
        return session
    
    def _decode_response(self, text: str) -> str:
        """Decode response từ Zefoy (base64 ngược)"""
        text = text.strip()
        if not text:
            return text
            
        try:
            # Thử decode base64 ngược
            reversed_val = text[::-1]
            url_decoded = urllib.parse.unquote(reversed_val)
            decoded = base64.b64decode(url_decoded).decode('utf-8')
            return decoded
        except:
            pass
            
        try:
            # Thử decode base64 thường
            decoded = base64.b64decode(text).decode('utf-8')
            return decoded
        except:
            pass
            
        return text
    
    def _parse_html_to_text(self, html_content: str) -> str:
        """Chuyển HTML thành text thuần"""
        soup = BeautifulSoup(html_content, 'html.parser')
        return soup.get_text(separator=' ').strip()
    
    def _extract_cooldown(self, html_content: str) -> Tuple[int, str]:
        """Trích xuất thời gian chờ từ response"""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Tìm countdown text
        countdown_tag = soup.find(id='login-countdown') or soup.find(class_=re.compile(r'countdown'))
        countdown_text = countdown_tag.text.strip() if countdown_tag else ""
        
        if not countdown_text:
            countdown_text = self._parse_html_to_text(html_content)
        
        # Parse minutes và seconds
        min_match = re.search(r'(\d+)\s*minute', countdown_text, re.IGNORECASE)
        sec_match = re.search(r'(\d+)\s*second', countdown_text, re.IGNORECASE)
        
        if min_match or sec_match:
            minutes = int(min_match.group(1)) if min_match else 0
            seconds = int(sec_match.group(1)) if sec_match else 0
            total = (minutes * 60) + seconds
            if total > 0:
                return total, f"Please wait {minutes} minute(s) {seconds} second(s)"
        
        # Tìm trong script
        js_patterns = [
            r'var\s+ltm\s*=\s*(\d+)',
            r'var\s+time\s*=\s*(\d+)',
            r'var\s+k\s*=\s*(\d+)',
            r'var\s+c\s*=\s*(\d+)'
        ]
        for pattern in js_patterns:
            match = re.search(pattern, html_content, re.IGNORECASE)
            if match:
                secs = int(match.group(1))
                if secs > 0:
                    return secs, f"Cooldown: {secs}s"
        
        return 0, ""
    
    def authenticate(self) -> bool:
        """Xác thực với Zefoy"""
        try:
            # Kiểm tra trang chủ
            response = self.session.get('https://zefoy.com/')
            html_content = response.text
            
            # Decode nếu cần
            decoded = self._decode_response(html_content)
            
            # Kiểm tra đã đăng nhập chưa
            if 't-followers-button' in decoded or 't-hearts-button' in decoded or 'colsmenu' in decoded:
                self.is_authenticated = True
                logger.info("✅ Authenticated successfully!")
                return True
                
            # Cần captcha
            logger.warning("⚠️ Captcha required or session expired")
            return False
            
        except Exception as e:
            logger.error(f"❌ Authentication error: {e}")
            return False
    
    def get_services(self) -> List[Dict]:
        """Lấy danh sách dịch vụ có sẵn"""
        try:
            response = self.session.get('https://zefoy.com/')
            html_content = self._decode_response(response.text)
            
            soup = BeautifulSoup(html_content, 'html.parser')
            cards = soup.find_all('div', class_='colsmenu')
            
            services = []
            for card in cards:
                title_tag = card.find('h5', class_='card-title')
                if not title_tag:
                    continue
                    
                title = title_tag.text.strip()
                btn = card.find('button')
                if not btn:
                    continue
                
                # Kiểm tra active
                is_active = 'disabled' not in btn.attrs
                
                # Lấy class của button
                btn_class = ""
                for cls in btn.get('class', []):
                    if cls.startswith('t-') and cls.endswith('-button'):
                        btn_class = cls
                        break
                
                # Status
                status_tag = card.find(class_='badge') or card.find('small')
                status_text = status_tag.text.strip() if status_tag else ("ON" if is_active else "OFF")
                
                services.append({
                    'name': title,
                    'active': is_active,
                    'status': status_text,
                    'btn_class': btn_class,
                    'menu_class': btn_class.replace('-button', '-menu') if btn_class else ""
                })
            
            self.services = services
            return services
            
        except Exception as e:
            logger.error(f"❌ Error getting services: {e}")
            return []
    
    def get_service_form(self, service: Dict) -> Optional[Dict]:
        """Lấy form cho dịch vụ cụ thể"""
        try:
            response = self.session.get('https://zefoy.com/')
            html_content = self._decode_response(response.text)
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Tìm menu của service
            menu_class = service.get('menu_class', '')
            if not menu_class:
                return None
            
            menu_div = soup.find('div', class_=menu_class)
            if not menu_div:
                # Thử tìm với regex
                menu_div = soup.find(class_=re.compile(menu_class))
            
            if not menu_div:
                return None
            
            # Tìm form
            form = menu_div.find('form')
            if not form:
                return None
            
            action = form.get('action', '')
            if action and not action.startswith('http'):
                action = f"https://zefoy.com/{action}"
            
            # Tìm input search
            search_input = form.find('input', type='search') or form.find('input', class_='form-control')
            input_name = search_input.get('name') if search_input else None
            
            if not input_name:
                for inp in form.find_all('input'):
                    inp_type = inp.get('type', 'text').lower()
                    if inp_type in ['search', 'text'] and inp.get('name'):
                        input_name = inp.get('name')
                        break
            
            return {
                'action': action,
                'input_name': input_name,
                'form': form
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting service form: {e}")
            return None
    
    def boost(self, video_url: str, service: Dict, max_runs: int = 1) -> Dict:
        """
        Thực hiện tăng tương tác
        
        Args:
            video_url: Link TikTok video hoặc profile
            service: Dịch vụ đã chọn
            max_runs: Số lần chạy tối đa
            
        Returns:
            Dict với kết quả
        """
        results = {
            'success': False,
            'message': '',
            'runs': 0,
            'errors': []
        }
        
        try:
            # Lấy form service
            form_info = self.get_service_form(service)
            if not form_info:
                results['message'] = "Cannot get service form"
                return results
            
            action_url = form_info['action']
            input_name = form_info['input_name']
            
            if not action_url or not input_name:
                results['message'] = "Invalid form data"
                return results
            
            # Headers cho AJAX
            ajax_headers = {
                'accept': '*/*',
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'origin': 'https://zefoy.com',
                'referer': 'https://zefoy.com/',
                'x-requested-with': 'XMLHttpRequest',
                'user-agent': self.user_agent,
            }
            
            runs = 0
            while runs < max_runs:
                try:
                    # 1. Gửi request tìm kiếm
                    search_data = {input_name: video_url}
                    search_resp = self.session.post(action_url, headers=ajax_headers, data=search_data)
                    decoded_search = self._decode_response(search_resp.text)
                    
                    # Kiểm tra cooldown
                    cooldown_sec, cooldown_msg = self._extract_cooldown(decoded_search)
                    if cooldown_sec > 0:
                        results['errors'].append(f"Cooldown: {cooldown_msg}")
                        results['message'] = f"Cooldown active: {cooldown_msg}"
                        return results
                    
                    # 2. Tìm form submit
                    soup = BeautifulSoup(decoded_search, 'html.parser')
                    submit_btn = soup.find('button', class_=re.compile(r'wbutton|btn'))
                    
                    if not submit_btn:
                        results['errors'].append("No submit button found")
                        results['message'] = "Cannot find submit button"
                        return results
                    
                    # 3. Lấy submit form
                    target_form = submit_btn.find_parent('form')
                    if not target_form:
                        results['errors'].append("Cannot find form")
                        results['message'] = "Cannot find submit form"
                        return results
                    
                    submit_action = target_form.get('action', '')
                    if submit_action and not submit_action.startswith('http'):
                        submit_action = f"https://zefoy.com/{submit_action}"
                    
                    # 4. Chuẩn bị data submit
                    submit_data = {}
                    for inp in target_form.find_all('input'):
                        name = inp.get('name')
                        val = inp.get('value', '')
                        if name:
                            submit_data[name] = val
                    
                    # Chọn giá trị tối đa cho select
                    selects = target_form.find_all('select')
                    for sel in selects:
                        name = sel.get('name')
                        if not name:
                            continue
                        options = sel.find_all('option')
                        max_val = None
                        max_int = -1
                        for opt in options:
                            val = opt.get('value', '').strip()
                            if not val:
                                continue
                            try:
                                val_int = int(val)
                                if val_int > max_int:
                                    max_int = val_int
                                    max_val = val
                            except ValueError:
                                if max_val is None:
                                    max_val = val
                        if max_val is not None:
                            submit_data[name] = max_val
                    
                    # 5. Submit boost
                    boost_resp = self.session.post(submit_action, headers=ajax_headers, data=submit_data)
                    decoded_boost = self._decode_response(boost_resp.text)
                    result_text = self._parse_html_to_text(decoded_boost)
                    
                    results['success'] = True
                    runs += 1
                    results['runs'] = runs
                    results['message'] = result_text or "Boost successful!"
                    
                    logger.info(f"✅ Boost #{runs}: {result_text}")
                    
                    # Nếu đạt đủ số lần
                    if runs >= max_runs:
                        break
                    
                    # Chờ trước lần tiếp theo
                    time.sleep(10)
                    
                except Exception as e:
                    error_msg = f"Error in boost loop: {e}"
                    results['errors'].append(error_msg)
                    logger.error(f"❌ {error_msg}")
                    break
            
            return results
            
        except Exception as e:
            results['message'] = f"Boost failed: {e}"
            logger.error(f"❌ {results['message']}")
            return results
    
    def auto_boost(self, video_url: str, service_name: str, max_runs: int = 10) -> Dict:
        """
        Tự động tăng tương tác
        
        Args:
            video_url: Link TikTok
            service_name: Tên dịch vụ (followers, hearts, views, etc.)
            max_runs: Số lượt chạy
            
        Returns:
            Dict với kết quả
        """
        # 1. Xác thực
        if not self.authenticate():
            return {
                'success': False,
                'message': 'Authentication failed. Cookie might be expired.'
            }
        
        # 2. Lấy danh sách dịch vụ
        services = self.get_services()
        if not services:
            return {
                'success': False,
                'message': 'Cannot get services list'
            }
        
        # 3. Tìm dịch vụ
        selected = None
        for s in services:
            if service_name.lower() in s['name'].lower():
                selected = s
                break
        
        if not selected:
            available = [s['name'] for s in services if s['active']]
            return {
                'success': False,
                'message': f'Service "{service_name}" not found. Available: {", ".join(available)}'
            }
        
        if not selected['active']:
            return {
                'success': False,
                'message': f'Service "{selected["name"]}" is currently offline/maintenance'
            }
        
        # 4. Thực hiện boost
        return self.boost(video_url, selected, max_runs)
    
    def get_status(self) -> Dict:
        """Lấy trạng thái của bot"""
        return {
            'authenticated': self.is_authenticated,
            'services': len(self.services),
            'cookie_valid': bool(self.cookie_string),
            'user_agent': self.user_agent[:50] + '...' if len(self.user_agent) > 50 else self.user_agent
        }
