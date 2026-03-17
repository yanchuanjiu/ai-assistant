"""
辅助脚本：列出飞书知识库空间列表，用于获取 FEISHU_WIKI_SPACE_ID。
运行方式：python -m tools.list_feishu_spaces
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from integrations.feishu.client import feishu_get

def main():
    resp = feishu_get("/wiki/v2/spaces")
    spaces = resp.get("data", {}).get("items", [])
    if not spaces:
        print("未找到知识库空间，请确认飞书应用已开通 wiki 权限。")
        return
    print("飞书知识库空间列表：")
    for s in spaces:
        print(f"  space_id={s['space_id']}  name={s['name']}")
    print("\n将 space_id 填入 .env 的 FEISHU_WIKI_SPACE_ID=")

if __name__ == "__main__":
    main()
