from flask import Flask, request, Response, jsonify
import requests
import threading
import time

# ================= 配置区域 =================
COSYVOICE_URL = "http://127.0.0.1:9880/"
# ===========================================

app = Flask(__name__)

# 全局锁：真正的线程锁
PROCESS_LOCK = threading.Lock()

print(f"[Bridge] 🚀 Flask 桥接服务启动 (同步多线程模式) -> {COSYVOICE_URL}")

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "ok",
        "locked": PROCESS_LOCK.locked(),
        "mode": "threading_sync"
    })

@app.route('/v1/audio/speech', methods=['POST'])
def openai_to_cosyvoice():
    # 1. 尝试获取锁
    # 这一步会阻塞当前线程，直到前一个请求释放锁
    # Flask 默认多线程，所以其他请求会在各自线程中等待，不会阻塞主线程（比如 Health 检查）
    print(f"[Bridge] ⏳ 线程 {threading.get_ident()} 等待获取锁...")
    with PROCESS_LOCK:
        print(f"[Bridge] 🔒 线程 {threading.get_ident()} 已获取锁，开始处理")
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "No JSON data"}), 400
                
            input_text = data.get("input", "")
            voice_name = data.get("voice", "胡桃")
            
            print(f"[IN] 收到请求: {input_text[:30]}...")

            payload = {
                "text": input_text,
                "speaker": voice_name,
                "speed": 1.0, 
                "stream": True # 强制流式
            }

            # 2. 发送同步请求 (stream=True)
            # 这里的 timeout 设置得长一点，防止生成慢导致断开
            try:
                resp = requests.post(COSYVOICE_URL, json=payload, stream=True, timeout=120)
            except Exception as e:
                print(f"[ERROR] 连接后端失败: {e}")
                return jsonify({"error": str(e)}), 502

            if resp.status_code != 200:
                print(f"[ERROR] 后端拒绝: {resp.status_code} - {resp.text}")
                return jsonify({"error": resp.text}), resp.status_code

            print(f"[OK] 🚀 开始流式传输...")

            # 3. 定义流生成器
            def generate():
                try:
                    # 转发数据块
                    for chunk in resp.iter_content(chunk_size=4096):
                        if chunk:
                            yield chunk
                except Exception as e:
                    print(f"[ERROR] 流传输异常: {e}")
                finally:
                    resp.close()
                    print(f"[Bridge] ✅ 线程 {threading.get_ident()} 完成")
                    # 注意：with PROCESS_LOCK 会在离开这个代码块时自动释放锁
                    # 但我们需要锁一直保持到生成器结束吗？
                    # 这是一个关键点！

            # 🚨 关键问题修正 🚨
            # with PROCESS_LOCK 会在 return Response 时就释放锁！
            # 这会导致流式传输还没结束，锁就释放了，造成并发冲突。
            # 我们必须手动管理锁，并在生成器结束时释放。

        except Exception as e:
            print(f"[ERROR] 处理异常: {e}")
            return jsonify({"error": str(e)}), 500

    # ❌ 这里的锁已经释放了，但流还在传输！
    # 必须重写逻辑，不能用 with PROCESS_LOCK
    
    # === 正确逻辑 ===
    return Response("Internal Error", 500) # 占位，下面的 write_to_file 会覆盖正确逻辑
