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
    "自定義...": "Custom", "1024x1024": "正方形 (1:1)", "1080x1080": "IG 貼文 (1:1)",
    "1080x1350": "IG 縱向 (4:5)", "1080x1920": "IG Story (9:16)", "1200x630": "FB 橫向 (1.91:1)",
}

def rerun_app():
    if hasattr(st, 'rerun'): st.rerun()
    elif hasattr(st, 'experimental_rerun'): st.experimental_rerun()
    else: st.stop()

st.set_page_config(page_title="FLUX AI (最終優化版)", page_icon="🏆", layout="wide")

# API 提供商
API_PROVIDERS = {
    "SiliconFlow": {"name": "SiliconFlow (免費)", "base_url_default": "https://api.siliconflow.cn/v1", "icon": "💧"},
    "NavyAI": {"name": "NavyAI", "base_url_default": "https://api.navy/v1", "icon": "⚓"},
    "Pollinations.ai": {"name": "Pollinations.ai (免費)", "base_url_default": "https://image.pollinations.ai", "icon": "🌸"},
    "OpenAI Compatible": {"name": "OpenAI 兼容 API", "base_url_default": "https://api.openai.com/v1", "icon": "🤖"},
}

# 基礎和動態發現的模型模式
BASE_FLUX_MODELS = {"flux.1-schnell": {"name": "FLUX.1 Schnell", "icon": "⚡", "priority": 1}}
FLUX_MODEL_PATTERNS = {
    r'flux[\.\-]?1[\.\-]?schnell': {"name": "FLUX.1 Schnell", "icon": "⚡", "priority": 100},
    r'flux[\.\-]?1[\.\-]?dev': {"name": "FLUX.1 Dev", "icon": "🔧", "priority": 200},
    r'flux[\.\-]?1[\.\-]?pro': {"name": "FLUX.1 Pro", "icon": "👑", "priority": 300},
}

# --- 核心函數 ---
def init_session_state():
    if 'api_profiles' not in st.session_state:
        st.session_state.api_profiles = {"預設 SiliconFlow": {'provider': 'SiliconFlow', 'api_key': '', 'base_url': 'https://api.siliconflow.cn/v1', 'validated': False}}
    if 'active_profile_name' not in st.session_state or st.session_state.active_profile_name not in st.session_state.api_profiles:
        st.session_state.active_profile_name = list(st.session_state.api_profiles.keys())[0]
    defaults = {'generation_history': [], 'favorite_images': [], 'discovered_models': {}}
    for key, value in defaults.items():
        if key not in st.session_state: st.session_state[key] = value

def get_active_config(): return st.session_state.api_profiles.get(st.session_state.active_profile_name, {})

def analyze_model_name(model_id: str) -> Dict:
    model_lower = model_id.lower()
    for pattern, info in FLUX_MODEL_PATTERNS.items():
        if re.search(pattern, model_lower):
            return {"name": info["name"], "icon": info["icon"], "priority": info["priority"]}
    return {"name": model_id.replace('-', ' ').replace('_', ' ').title(), "icon": "🤖", "priority": 999}

def auto_discover_flux_models(client) -> Dict[str, Dict]:
    discovered_models = {}
    try:
        models = client.models.list().data
        for model in models:
            if 'flux' in model.id.lower(): # 嚴格篩選包含 'flux' 的模型
                model_info = analyze_model_name(model.id)
                discovered_models[model.id] = model_info
        return discovered_models
    except Exception as e:
        st.warning(f"模型發現失敗: {e}")
        return {}

def merge_models() -> Dict[str, Dict]:
    merged_models = {**BASE_FLUX_MODELS, **st.session_state.get('discovered_models', {})}
    return dict(sorted(merged_models.items(), key=lambda item: item[1].get('priority', 999)))

def validate_api_key(api_key: str, base_url: str, provider: str) -> Tuple[bool, str]:
    if provider == "Pollinations.ai": return True, "Pollinations.ai 無需驗證"
    try:
        OpenAI(api_key=api_key, base_url=base_url).models.list()
        return True, "API 密鑰驗證成功"
    except Exception as e: return False, f"API 驗證失敗: {e}"

def generate_images_with_retry(client, **params) -> Tuple[bool, any]:
    # ... (生成邏輯與之前相同) ...
    return True, "生成成功（模擬）"

def init_api_client():
    cfg = get_active_config()
    if cfg.get('api_key') and cfg.get('provider') != "Pollinations.ai":
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
        current_provider = active_config.get('provider', 'SiliconFlow')
        sel_prov_name = st.selectbox("API 提供商", provs, index=provs.index(current_provider), format_func=lambda x: f"{API_PROVIDERS[x]['icon']} {API_PROVIDERS[x]['name']}")
        
        # 優化：僅在提供商確實改變時才更新 URL
        if sel_prov_name != current_provider:
            active_config['base_url'] = API_PROVIDERS[sel_prov_name]['base_url_default']
        
        api_key_input = st.text_input("API 密鑰", value=active_config.get('api_key', ''), type="password", disabled=(sel_prov_name == "Pollinations.ai"))
        base_url_input = st.text_input("API 端點 URL", value=active_config.get('base_url', API_PROVIDERS[sel_prov_name]['base_url_default']))

    st.markdown("---")
    profile_name_input = st.text_input("存檔名稱", value=st.session_state.active_profile_name)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("💾 保存/更新存檔", type="primary"):
            new_config = {'provider': sel_prov_name, 'api_key': api_key_input, 'base_url': base_url_input}
            is_valid, msg = validate_api_key(new_config['api_key'], new_config['base_url'], new_config['provider'])
            new_config['validated'] = is_valid
            st.session_state.api_profiles[profile_name_input] = new_config
            st.session_state.active_profile_name = profile_name_input
            st.success(f"✅ 存檔 '{profile_name_input}' 已保存。驗證: {'成功' if is_valid else f'失敗 ({msg})'}")
            time.sleep(1); rerun_app()
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
        if st.button("🔍 發現 FLUX 模型", use_container_width=True, disabled=(cfg['provider'] == "Pollinations.ai")):
            with st.spinner("🔍 正在發現模型..."):
                discovered = auto_discover_flux_models(client)
                st.session_state.discovered_models = discovered
                st.success(f"發現 {len(discovered)} 個 FLUX 模型！") if discovered else st.warning("未發現任何 FLUX 模型。")
                time.sleep(1); rerun_app()
    else: st.error(f"🔴 '{st.session_state.active_profile_name}' 未驗證")
    st.markdown("---")
    st.info(f"⚡ **免費版優化**\n- 歷史: {MAX_HISTORY_ITEMS}\n- 收藏: {MAX_FAVORITE_ITEMS}")

st.title("🏆 FLUX AI (最終優化版)")

# --- 主介面 ---
tab1, tab2, tab3 = st.tabs(["🚀 生成圖像", f"📚 歷史", f"⭐ 收藏"])

with tab1:
    if not api_configured: st.warning("⚠️ 請在側邊欄選擇一個已驗證的存檔。")
    else:
        all_models = merge_models()
        if not all_models: st.warning("⚠️ 未發現模型，請點擊「發現 FLUX 模型」。")
        else:
            sel_model = st.selectbox("模型:", list(all_models.keys()), format_func=lambda x: f"{all_models[x].get('icon', '🤖')} {all_models[x].get('name', x)}")
            # ... (其餘 UI 邏輯與之前相同) ...
            if st.button("🚀 生成圖像", type="primary", use_container_width=True):
                # ... (生成邏輯不變) ...
                st.success("圖像生成成功！（模擬）")

# ... (歷史和收藏夾標籤的內容與之前相同) ...

st.markdown("""<div style="text-align: center; color: #888; margin-top: 2rem;"><small>🏆 最終優化版 | 部署在 Koyeb 免費實例 🏆</small></div>""", unsafe_allow_html=True)
