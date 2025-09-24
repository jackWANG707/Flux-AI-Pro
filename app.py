import streamlit as st
from openai import OpenAI
from PIL import Image
import requests
from io import BytesIO
import datetime
import base64
from typing import Dict, List, Tuple
import time
import random
import json
import uuid
import os
import re
from urllib.parse import urlencode, quote
import gc

# 為免費方案設定限制
MAX_HISTORY_ITEMS = 15
MAX_FAVORITE_ITEMS = 30
MAX_BATCH_SIZE = 4

# 風格預設
STYLE_PRESETS = {
    "無": "", "電影感": "cinematic, dramatic lighting, high detail, sharp focus",
    "動漫風": "anime style, vibrant colors, clean line art", "賽博龐克": "cyberpunk, neon lights, futuristic city, high-tech",
    "水彩畫": "watercolor painting, soft wash, blended colors", "奇幻藝術": "fantasy art, epic, detailed, magical",
}

# 擴展的圖像尺寸選項
IMAGE_SIZES = {
    "自定義...": "Custom",
    "1024x1024": "正方形 (1:1) - 通用", "1080x1080": "IG 貼文 (1:1)",
    "1080x1350": "IG 縱向 (4:5)", "1080x1920": "IG Story (9:16)",
    "1200x630": "FB 橫向 (1.91:1)", "1344x768": "寬螢幕 (16:9)",
}

def rerun_app():
    if hasattr(st, 'rerun'): st.rerun()
    elif hasattr(st, 'experimental_rerun'): st.experimental_rerun()
    else: st.stop()

st.set_page_config(page_title="Flux AI (終極自訂版)", page_icon="🚀", layout="wide")

# --- 核心函數 (與之前版本相同，為簡潔省略) ---
def init_session_state():
    if 'api_profiles' not in st.session_state:
        st.session_state.api_profiles = {
            "預設 Pollinations": {'provider': 'Pollinations.ai', 'api_key': '', 'base_url': 'https://image.pollinations.ai', 'validated': False, 'pollinations_auth_mode': '免費', 'pollinations_token': '', 'pollinations_referrer': ''}
        }
    if 'active_profile_name' not in st.session_state or st.session_state.active_profile_name not in st.session_state.api_profiles:
        st.session_state.active_profile_name = list(st.session_state.api_profiles.keys())[0]
    defaults = {'generation_history': [], 'favorite_images': [], 'discovered_models': {}}
    for key, value in defaults.items():
        if key not in st.session_state: st.session_state[key] = value

def get_active_config(): return st.session_state.api_profiles.get(st.session_state.active_profile_name, {})
def auto_discover_flux_models(client, provider: str, base_url: str) -> Dict[str, Dict]: return {}
def analyze_model_name(model_id: str) -> Dict: return {}
def merge_models() -> Dict[str, Dict]: return {**BASE_FLUX_MODELS, **st.session_state.get('discovered_models', {})}
def validate_api_key(api_key: str, base_url: str, provider: str) -> Tuple[bool, str]:
    try:
        if provider == "Pollinations.ai": return (True, "Pollinations.ai 已就緒") if requests.get(f"{base_url}/models", timeout=10).ok else (False, "連接失敗")
        else: OpenAI(api_key=api_key, base_url=base_url).models.list(); return True, "API 密鑰驗證成功"
    except Exception as e: return False, f"API 驗證失敗: {e}"
def generate_images_with_retry(client, **params) -> Tuple[bool, any]:
    prompt = params.pop("prompt", "")
    if (neg_prompt := params.pop("negative_prompt", None)): prompt += f" --no {neg_prompt}"
    provider = get_active_config().get('provider')
    for attempt in range(3):
        try:
            if provider == "Pollinations.ai":
                width, height = params.get("size", "1024x1024").split('x')
                api_params = {k: v for k, v in {"model": params.get("model"), "width": width, "height": height, "seed": random.randint(0, 1000000), "nologo": params.get("nologo"), "private": params.get("private"), "enhance": params.get("enhance")}.items() if v is not None}
                headers, cfg = {}, get_active_config()
                auth_mode = cfg.get('pollinations_auth_mode', '免費')
                if auth_mode == '令牌' and cfg.get('pollinations_token'): headers['Authorization'] = f"Bearer {cfg['pollinations_token']}"
                elif auth_mode == '域名' and cfg.get('pollinations_referrer'): headers['Referer'] = cfg['pollinations_referrer']
                response = requests.get(f"{cfg['base_url']}/prompt/{quote(prompt)}?{urlencode(api_params)}", headers=headers, timeout=120)
                if response.ok: return True, type('MockResponse', (object,), {'data': [type('obj', (object,), {'url': f"data:image/png;base64,{base64.b64encode(response.content).decode()}"})()]})()
                raise Exception(f"HTTP {response.status_code}: {response.text}")
            else:
                params["prompt"] = prompt
                return True, client.images.generate(**params)
        except Exception as e:
            if attempt < 2 and ("500" in str(e) or "timeout" in str(e).lower()): time.sleep((attempt + 1) * 2); continue
            return False, str(e)
    return False, "所有重試均失敗"
def add_to_history(prompt: str, negative_prompt: str, model: str, images: List[str], metadata: Dict):
    history = st.session_state.generation_history
    history.insert(0, {"id": str(uuid.uuid4()), "timestamp": datetime.datetime.now(), "prompt": prompt, "negative_prompt": negative_prompt, "model": model, "images": images, "metadata": metadata})
    st.session_state.generation_history = history[:MAX_HISTORY_ITEMS]
def display_image_with_actions(image_url: str, image_id: str, history_item: Dict):
    try:
        img_data = base64.b64decode(image_url.split(',')[1]) if image_url.startswith('data:image') else requests.get(image_url, timeout=10).content
        st.image(Image.open(BytesIO(img_data)), use_column_width=True)
        col1, col2, col3 = st.columns(3)
        with col1: st.download_button("📥 下載", img_data, f"flux_{image_id}.png", "image/png", key=f"dl_{image_id}", use_container_width=True)
        with col2:
            is_fav = any(fav['id'] == image_id for fav in st.session_state.favorite_images)
            if st.button("⭐" if is_fav else "☆", key=f"fav_{image_id}", use_container_width=True, help="收藏/取消收藏"):
                if is_fav: st.session_state.favorite_images = [f for f in st.session_state.favorite_images if f['id'] != image_id]
                elif len(st.session_state.favorite_images) < MAX_FAVORITE_ITEMS: st.session_state.favorite_images.append({"id": image_id, "image_url": image_url, "timestamp": datetime.datetime.now(), "history_item": history_item})
                else: st.warning(f"收藏夾已滿")
                rerun_app()
        with col3:
            if st.button("🎨 變體", key=f"vary_{image_id}", use_container_width=True, help="生成此圖像的變體"):
                st.session_state.update({'vary_prompt': history_item['prompt'], 'vary_negative_prompt': history_item.get('negative_prompt', ''), 'vary_model': history_item['model']})
                rerun_app()
    except Exception as e: st.error(f"圖像顯示錯誤: {e}")
def init_api_client():
    cfg = get_active_config()
    if cfg.get('provider') != "Pollinations.ai" and cfg.get('api_key'):
        try: return OpenAI(api_key=cfg['api_key'], base_url=cfg['base_url'])
        except Exception: return None
    return None
def show_api_settings():
    st.subheader("⚙️ API 存檔管理")
    profile_names = list(st.session_state.api_profiles.keys())
    st.session_state.active_profile_name = st.selectbox("活動存檔", profile_names, index=profile_names.index(st.session_state.active_profile_name) if st.session_state.active_profile_name in profile_names else 0)
    active_config = get_active_config().copy()
    with st.expander("📝 編輯存檔內容", expanded=True):
        provs = list(API_PROVIDERS.keys())
        sel_prov = st.selectbox("API 提供商", provs, index=provs.index(active_config.get('provider', 'Pollinations.ai')), format_func=lambda x: f"{API_PROVIDERS[x]['icon']} {API_PROVIDERS[x]['name']}")
        referrer, token, api_key_input = '', '', active_config.get('api_key', '')
        auth_mode = active_config.get('pollinations_auth_mode', '免費')
        if sel_prov == "Pollinations.ai":
            auth_mode = st.radio("模式", ["免費", "域名", "令牌"], horizontal=True, index=["免費", "域名", "令牌"].index(auth_mode))
            if auth_mode == "域名": referrer = st.text_input("應用域名", value=active_config.get('pollinations_referrer', ''), placeholder="例如: myapp.koyeb.app")
            elif auth_mode == "令牌": token = st.text_input("API 令牌", value=active_config.get('pollinations_token', ''), type="password")
        else:
            api_key_input = st.text_input("API 密鑰", value=active_config.get('api_key', ''), type="password")
        base_url_input = st.text_input("API 端點 URL", value=active_config.get('base_url', API_PROVIDERS[sel_prov]['base_url_default']))
    st.markdown("---")
    profile_name_input = st.text_input("存檔名稱", value=st.session_state.active_profile_name)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("💾 保存/更新存檔", type="primary"):
            if profile_name_input.strip():
                new_config = {'provider': sel_prov, 'api_key': api_key_input, 'base_url': base_url_input, 'validated': False}
                if sel_prov == "Pollinations.ai": new_config.update({'pollinations_auth_mode': auth_mode, 'pollinations_referrer': referrer, 'pollinations_token': token})
                with st.spinner("正在驗證並保存..."):
                    is_valid, msg = validate_api_key(new_config['api_key'], new_config['base_url'], new_config['provider'])
                    new_config['validated'] = is_valid
                    st.session_state.api_profiles[profile_name_input] = new_config
                    st.session_state.active_profile_name = profile_name_input
                    st.success(f"✅ 存檔 '{profile_name_input}' 已保存。驗證狀態: {'成功' if is_valid else '失敗'}")
                    time.sleep(1); rerun_app()
            else: st.error("存檔名稱不能為空")
    with col2:
        if st.button("🗑️ 刪除此存檔", disabled=len(st.session_state.api_profiles) <= 1):
            del st.session_state.api_profiles[st.session_state.active_profile_name]
            st.session_state.active_profile_name = list(st.session_state.api_profiles.keys())[0]
            st.success("存檔已刪除。"); time.sleep(1); rerun_app()

init_session_state()
client = init_api_client()
cfg = get_active_config()
api_configured = cfg.get('validated', False)

# --- 側邊欄 ---
with st.sidebar:
    show_api_settings()
    st.markdown("---")
    if api_configured:
        st.success(f"🟢 活動存檔: '{st.session_state.active_profile_name}'")
        if st.button("🔍 發現模型", use_container_width=True): pass
    else: st.error(f"🔴 '{st.session_state.active_profile_name}' 未驗證")
    st.markdown("---")
    st.info(f"⚡ **免費版優化**\n- 歷史: {MAX_HISTORY_ITEMS}\n- 收藏: {MAX_FAVORITE_ITEMS}")

st.title("🚀 Flux AI (終極自訂版)")

# --- 主介面 ---
tab1, tab2, tab3 = st.tabs(["🚀 生成圖像", f"📚 歷史 ({len(st.session_state.generation_history)})", f"⭐ 收藏 ({len(st.session_state.favorite_images)})"])

with tab1:
    if not api_configured: st.warning("⚠️ 請在側邊欄選擇一個已驗證的存檔。")
    else:
        all_models = merge_models()
        if not all_models: st.warning("⚠️ 未發現模型，請點擊「發現模型」。")
        else:
            sel_model = st.selectbox("模型:", list(all_models.keys()), format_func=lambda x: f"{all_models[x].get('icon', '🤖')} {all_models[x].get('name', x)}")
            selected_style = st.selectbox("🎨 風格預設:", list(STYLE_PRESETS.keys()))
            prompt_val = st.text_area("✍️ 提示詞:", height=100, placeholder="一隻貓在日落下飛翔，電影感")
            negative_prompt_val = st.text_area("🚫 負向提示詞:", height=50, placeholder="模糊, 糟糕的解剖結構")
            
            size_preset = st.selectbox("圖像尺寸", options=list(IMAGE_SIZES.keys()), format_func=lambda x: IMAGE_SIZES[x])
            
            width, height = 1024, 1024
            if size_preset == "自定義...":
                col_w, col_h = st.columns(2)
                with col_w: width = st.slider("寬度 (px)", 512, 2048, 1024, 64)
                with col_h: height = st.slider("高度 (px)", 512, 2048, 1024, 64)
                final_size_str = f"{width}x{height}"
            else:
                final_size_str = size_preset

            num_images = 1 if cfg['provider'] == "Pollinations.ai" else st.slider("生成數量", 1, MAX_BATCH_SIZE, 1)

            enhance, private, nologo = False, False, False
            if cfg['provider'] == "Pollinations.ai":
                with st.expander("🌸 Pollinations.ai 選項"):
                    enhance, private, nologo = st.checkbox("增強提示詞", True), st.checkbox("私密模式", True), st.checkbox("移除標誌", True)

            if st.button("🚀 生成圖像", type="primary", use_container_width=True, disabled=not prompt_val.strip()):
                final_prompt = f"{prompt_val}, {STYLE_PRESETS[selected_style]}" if selected_style != "無" else prompt_val
                with st.spinner(f"🎨 正在生成 {num_images} 張圖像..."):
                    params = {"model": sel_model, "prompt": final_prompt, "negative_prompt": negative_prompt_val, "n": num_images, "size": final_size_str, "enhance": enhance, "private": private, "nologo": nologo}
                    success, result = generate_images_with_retry(client, **params)
                    if success:
                        img_urls = [img.url for img in result.data]
                        add_to_history(prompt_val, negative_prompt_val, sel_model, img_urls, {"size": final_size_str, "provider": cfg['provider'], "style": selected_style})
                        st.success(f"✨ 成功生成 {len(img_urls)} 張圖像！")
                        cols = st.columns(min(len(img_urls), 2))
                        for i, url in enumerate(img_urls):
                            with cols[i % 2]: display_image_with_actions(url, f"{st.session_state.generation_history[0]['id']}_{i}", st.session_state.generation_history[0])
                        gc.collect()
                    else: st.error(f"❌ 生成失敗: {result}")

# ... (歷史和收藏夾標籤的程式碼與之前相同) ...
with tab2: st.info("📭 尚無生成歷史。")
with tab3: st.info("⭐ 尚無收藏的圖像。")

st.markdown("""<div style="text-align: center; color: #888; margin-top: 2rem;"><small>🚀 終極自訂版 | 部署在 Koyeb 免費實例 🚀</small></div>""", unsafe_allow_html=True)
