import io
import csv
import json
from datetime import datetime
from typing import List, Dict, Any, Tuple
import streamlit as st
import base64
import re

# =========================
# HAR 解析与数据提取
# =========================

def har_bytes_to_json(raw: bytes) -> Dict[str, Any] | None:
    """将 HAR 文件字节解析为 JSON 对象。"""
    if not raw:
        return None
    try:
        text = raw.decode("utf-8", errors="ignore")
        return json.loads(text)
    except Exception:
        return None


def decode_content(content):
    """与 app.py 中一致：尝试不同方式解码响应文本为 JSON。"""
    if not content:
        return None

    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

    encodings = ['utf-8', 'latin1', 'cp1252', 'ascii']

    if isinstance(content, str):
        try:
            decoded = base64.b64decode(content)
            for encoding in encodings:
                try:
                    text = decoded.decode(encoding)
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        pass
                except UnicodeDecodeError:
                    pass
        except Exception:
            pass

    if isinstance(content, (bytes, bytearray)):
        for encoding in encodings:
            try:
                text = content.decode(encoding)
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    pass
            except UnicodeDecodeError:
                pass

    return None


def extract_posts(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    posts: List[Dict[str, Any]] = []
    try:
        if not isinstance(data, dict) or 'data' not in data:
            return posts
        data = data['data']
        if 'objects' in data:
            for post in data['objects']:
                if 'accountInfo' in post and isinstance(post['accountInfo'], dict):
                    posts.append(post)
    except Exception:
        pass
    return posts


def extract_data(har_data: Dict[str, Any], config: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int]:
    """遍历 HAR entries，解码响应，提取帖子并按字段映射输出。"""
    extracted_data: List[Dict[str, Any]] = []
    valid_posts = 0

    if not har_data or 'log' not in har_data or 'entries' not in har_data['log']:
        return extracted_data, valid_posts

    entries = har_data['log']['entries']

    for entry in entries:
        try:
            if 'response' not in entry or 'content' not in entry['response']:
                continue
            content = entry['response']['content']
            if not content.get('text'):
                continue
            mime_type = content.get('mimeType', 'unknown')
            if mime_type == 'image/jpg':
                continue

            data = decode_content(content.get('text', ''))
            if not data:
                continue

            posts = extract_posts(data)
            for post in posts:
                valid_posts += 1
                post_data: Dict[str, Any] = {}
                for field, path in config['fields'].items():
                    try:
                        value: Any = post
                        for key in path.split('.'):
                            if isinstance(value, dict):
                                value = value.get(key, {})
                            else:
                                value = {}
                                break
                        post_data[field] = value if value != {} else ''
                    except Exception:
                        post_data[field] = ''

                # 将 Description 拆分为 Title 和 Tags（与 app.py 相同规则）
                description = post_data.get('Description', '')
                if description:
                    raw = description
                    tokens = re.findall(r'(?:#|@)[^\s#@]+', raw)
                    if not tokens and raw[:1].isspace():
                        title = raw.strip()
                        tags = ''
                    else:
                        title = re.sub(r'(?:#|@)[^\s#@]+', '', raw).strip()
                        hashtags = [t for t in tokens if t.startswith('#')]
                        mentions = [t for t in tokens if t.startswith('@')]
                        tag_groups: List[str] = []
                        if hashtags:
                            tag_groups.append(''.join(hashtags))
                        if mentions:
                            tag_groups.append(' '.join(mentions))
                        tags = ' '.join(tag_groups)
                    post_data['Title'] = title
                    post_data['Tags'] = tags
                else:
                    post_data.setdefault('Title', '')
                    post_data.setdefault('Tags', '')

                final_post_data = {
                    'Title': post_data.get('Title', ''),
                    'Tags': post_data.get('Tags', ''),
                    'Create Time': post_data.get('Create Time', ''),
                    'Likes': post_data.get('Likes', ''),
                    'Comments': post_data.get('Comments', ''),
                    'Shares': post_data.get('Shares', ''),
                    'Favorites': post_data.get('Favorites', ''),
                    'Account Nickname': post_data.get('Account Nickname', ''),
                    'Account Username': post_data.get('Account Username', ''),
                    'Cover URL': post_data.get('Cover URL', ''),
                    'Nonce': post_data.get('Nonce', '')
                }
                extracted_data.append(final_post_data)
        except Exception:
            continue

    return extracted_data, valid_posts


# =========================
# CSV 导出（UTF-8-SIG）
# =========================

def to_csv_bytes(rows: List[Dict[str, Any]]) -> bytes:
    """将结果行写成 CSV（二进制，UTF-8-SIG）。"""
    if not rows:
        return b''

    # 转换时间戳为易读时间（YYYY-MM-DD HH:MM:SS）
    safe_rows: List[Dict[str, Any]] = []
    for r in rows:
        r = dict(r)
        ts = r.get('Create Time')
        if isinstance(ts, (int, float)) or (isinstance(ts, str) and ts.isdigit()):
            try:
                r['Create Time'] = datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                r['Create Time'] = ''
        safe_rows.append(r)

    # 与 app.py#L241-253 一致的字段顺序
    field_order = [
        'Title',
        'Tags',
        'Create Time',
        'Likes',
        'Comments',
        'Shares',
        'Favorites',
        'Account Nickname',
        'Account Username',
        'Cover URL',
        'Nonce'
    ]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=field_order, quoting=csv.QUOTE_ALL)
    writer.writeheader()
    writer.writerows(safe_rows)
    return buf.getvalue().encode('utf-8-sig')


# =========================
# Streamlit 界面（中文）
# =========================

st.set_page_config(page_title="HAR 转 CSV", page_icon="📦", layout="centered")
st.title("📦 HAR 转 CSV")
st.markdown(
    "上传一个或多个 `.har` 文件（从浏览器开发者工具的 **Network** 面板导出）。"
    "应用会扫描响应内容，提取微信帖子字段并合并为一份 CSV。"
)

uploaded = st.file_uploader(
    "拖拽或选择 `.har` 文件（可多选）",
    type=["har"],
    accept_multiple_files=True,
    help="Chrome/Edge：打开开发者工具 → Network → 右键空白处 → Save all as HAR with content。"
)

run_btn = st.button("开始处理")

if run_btn:
    if not uploaded:
        st.warning("请至少上传 1 个 `.har` 文件。")
        st.stop()

    all_rows: List[Dict[str, Any]] = []
    progress = st.progress(0)

    # 字段映射配置（与 app.py 保持一致）
    config = {
        'fields': {
            'Create Time': 'createTime',
            'Likes': 'likeCount',
            'Comments': 'commentCount',
            'Shares': 'forwardCount',
            'Favorites': 'favCount',
            'Account Username': 'accountInfo.username',
            'Account Nickname': 'accountInfo.nickName',
            'Description': 'description',
            'Cover URL': 'coverUrl',
            'Nonce': 'nonce'
        }
    }

    for i, uf in enumerate(uploaded, start=1):
        with st.status(f"正在处理 **{uf.name}** …", expanded=False):
            raw = uf.read()
            har_obj = har_bytes_to_json(raw)
            if not har_obj:
                st.error(f"无法解析 HAR：{uf.name}")
            else:
                rows, count = extract_data(har_obj, config)
                all_rows.extend(rows)
                st.write(f"在该文件中发现 **{count}** 条帖子。")

        progress.progress(i / len(uploaded))

    if not all_rows:
        st.info("未在所上传的文件中找到可用的帖子数据。")
        st.stop()

    # 导出 CSV
    csv_bytes = to_csv_bytes(all_rows)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = f"weixin_posts_{ts}.csv"

    st.success(f"完成！共从 **{len(uploaded)}** 个文件提取 **{len(all_rows)}** 条记录。")
    st.download_button("⬇️ 下载合并后的 CSV", data=csv_bytes, file_name=out_name, mime="text/csv")

    # 预览区
    with st.expander("预览数据（前 N 行）"):
        max_n = len(all_rows)
        default_n = min(1000, max_n)
        n = st.number_input("选择要预览的行数（从 1 开始）", min_value=1, max_value=max_n, value=default_n, step=100)
        st.dataframe(all_rows[:n], use_container_width=True)