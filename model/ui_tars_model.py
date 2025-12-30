from tqdm import tqdm
import os, json, base64, ast
from openai import OpenAI

import json

import re

def extract_ele_loc(obj):
    """
    从各种格式的 ele_loc 输出中提取 (x, y) 坐标
    支持：
      - "(1263,137)"
      - [879, 53]
      - '{"ele_loc": "(1275,398)"}'
    返回：tuple(int, int) 或 (None, None)
    """
    # 如果输入是 None
    if obj is None:
        return -1, -1

    # 如果是字符串，可能是 JSON，也可能是 "(x,y)"
    if isinstance(obj, str):
        s = obj.strip()

        # 如果是 JSON 字符串
        if s.startswith("{") and s.endswith("}"):
            try:
                parsed = json.loads(s)
                # 递归调用自身，提取内部 ele_loc
                return extract_ele_loc(parsed.get("ele_loc"))
            except Exception:
                pass

        # 直接在字符串中匹配数字
        nums = re.findall(r"\d+", s)
        if len(nums) >= 2:
            return int(nums[0]), int(nums[1])
        else:
            return -1, -1

    # 如果是列表
    elif isinstance(obj, list):
        if len(obj) >= 2 and all(isinstance(x, (int, float, str)) for x in obj):
            try:
                return int(obj[0]), int(obj[1])
            except Exception:
                return -1, -1
        else:
            return -1, -1

    # 如果是字典
    elif isinstance(obj, dict):
        # 若本身就有 x, y 键
        if "x" in obj and "y" in obj:
            return int(obj["x"]), int(obj["y"])
        elif "ele_loc" in obj:
            return extract_ele_loc(obj["ele_loc"])
        else:
            return -1, -1

    else:
        return -1, -1

def extract_pred_official(response):
    """
    将模型返回的 response 转换为标准的 pred 格式
    主要处理 ele_loc 字段格式 "(x, y)" -> {"x": x, "y": y}
    """
    # 如果是字符串，尝试解析
    # print(response)
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except json.JSONDecodeError:
            print("× response JSON 解析失败，原始内容:")
            # print("####################################")
            return None

    # 如果不是字典，返回错误格式
    if not isinstance(response, dict):
        print("× response 格式异常，非 dict：", response)
        return {
            "ele_loc": {"x": -1, "y": -1},
            "ele_type": "",
            "action": {"type": "", "content": ""}
        }

    # 提取 ele_loc，处理 "(x, y)" 格式
    ele_loc_str = response.get("ele_loc", "")
    if isinstance(ele_loc_str, str):
        try:
            # 尝试将 "(x, y)" 字符串转换为字典形式 {"x": x, "y": y}
            ele_loc = ast.literal_eval(ele_loc_str)  # 将字符串转为元组 (x, y)
            if isinstance(ele_loc, tuple) and len(ele_loc) == 2:
                ele_loc = {"x": ele_loc[0], "y": ele_loc[1]}
            else:
                ele_loc = {"x": -1, "y": -1}  # 如果解析失败，返回默认值
        except:
            print("× ele_loc 格式错误:", ele_loc_str)
            ele_loc = {"x": -1, "y": -1}
    else:
        ele_loc = {"x": -1, "y": -1}

    # 提取 ele_type 和 action（处理异常情况）
    ele_type = response.get("ele_type", "")
    action = response.get("action", {})

    
    if isinstance(action, dict):
        action_type_pre = action.get("type", "")
        if(action_type_pre=="type"): 
            action_type="input"
        else:
            action_type=action_type_pre
    else:
        action_type = ""
    

    pred = {
        "ele_loc": ele_loc,
        "ele_type": ele_type if isinstance(ele_type, str) else "",
        "action": {
            "type": action_type,
            "content": action.get("content", "") if isinstance(action, dict) else ""
        }
    }

    return pred

def get_image_format(base64_image):
    header = base64_image[:20]  # 更长前缀更安全
    if header.startswith("iVBOR"):
        return "png"
    elif header.startswith("/9j/"):
        return "jpeg"
    elif header.startswith("R0lG"):
        return "gif"
    else:
        return "unknown"

def generate_data_uri(base64_image):
    img_format = get_image_format(base64_image)
    if img_format == "unknown":
        raise ValueError("Unsupported or unknown image format")
    # print(f"data:image/{img_format};base64,")
    return f"data:image/{img_format};base64,{base64_image}"


class UI_TARS:

    def __init__(
        self, 
        api_key="hf_xxx", 	## TODO: 替换为自己的api
        base_url="https://xxx.endpoints.huggingface.cloud/v1/",		## TODO: 替换为自己的endpoint
        prompt_step_file = "prompt_UTS_step_given.txt",
        prompt_task_file = "prompt_UTS_task_given.txt",
        prompt_task_abn_file = "prompt_UTS_task_given_abnormal.txt"
    ):
        self.api_key = api_key
        self.base_url = base_url
        prompt_step_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), prompt_step_file)
        prompt_task_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), prompt_task_file)
        prompt_task_abn_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), prompt_task_abn_file)

        with open(prompt_step_path, 'r', encoding='utf-8') as f:
            prompt_step = f.read()
        with open(prompt_task_path, 'r', encoding='utf-8') as f:
            prompt_task = f.read()
        with open(prompt_task_abn_path, 'r', encoding='utf-8') as f:
            prompt_task_abn = f.read()

        self.prompt_step = prompt_step
        self.prompt_task = prompt_task
        self.prompt_task_abn = prompt_task_abn

        self.client = OpenAI(
            base_url=self.base_url, 
            api_key=self.api_key
        )

    def pred_step_loc(self, step_description, base64_image):
        """
        pred = {
            "ele_loc":{
                "x": ,
                "y":
            },
            "ele_type":
            "action":{
                "type": ,
                "content":
            }
        }
        """
        # print("Im UI-TARS")
        data_uri = generate_data_uri(base64_image)
        messages=[
            {
                "role": "system",
                "content": [{"type": "text", "text": self.prompt_step}]},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": step_description},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_uri},
                    }
                ]
            }
        ]
        # print(messages)
        chat_completion = self.client.chat.completions.create(
                model="tgi",
                messages=messages,
                top_p=None,
                temperature=0.0,
                max_tokens=400,
                stream=True,
                seed=None,
                stop=None,
                frequency_penalty=None,
                presence_penalty=None
            )

        response = ""
        for message in chat_completion:
            response += message.choices[0].delta.content
        # print(response)

        pred = extract_pred_official(response)

        return pred

    def pred_task_full(self, task_description, base64_image_list):
        """
        完整的任务预测函数，处理多张base64图像的输入并与模型交互，
        每次将历史信息添加到messages中
        """
        # 初始化messages
        
        # 保存历史记录
        history = []
        preds = []
        
        # 遍历所有base64图像并逐步推理
        # print(base64_image_list)
        # print(len(base64_image_list))
        for base64_image in base64_image_list:
            # 在当前消息中添加新的图片并向模型请求预测
            # print(base64_image)
            data_uri = generate_data_uri(base64_image)
            messages = [
                {
                    "role": "system",
                    "content": [{"type": "text", "text": self.prompt_task_abn}]
                }] + history + [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": task_description},
                        # 初始图像可以是第一张
                        {"type": "image_url", "image_url": {"url": data_uri}} 
                    ]
                }
            ]
            
            # if history:
            #     # 将历史记录作为assistant的消息添加
            #     for past_response in history:
            #         messages.append({
            #             "role": "assistant",
            #             "content": [{"type": "text", "text": past_response}]
            #         })
            
            # print(len(messages))

            # 调用模型获取输出
            chat_completion = self.client.chat.completions.create(
                model="tgi",  # 需要根据实际模型调整
                messages=messages,
                top_p=None,
                temperature=0.0,
                max_tokens=400,
                stream=True
            )
            
            # 从模型的响应中提取内容
            response = ""
            for message in chat_completion:
                response += message.choices[0].delta.content

            assistant_message = {
                "role": "assistant",
                "content": [{"type": "text", "text": response}]
            }
            history.append(assistant_message)
            
            pred = extract_pred_official(response)
            
            if(pred==None):
                return None
            # 输出模型返回内容，作为下一轮输入的历史记录
            preds.append(pred)
        
        return preds

    def pred_task_ground(self, preds_0, base64_image_list):
        """
        完整的任务预测函数，处理多张base64图像的输入并与模型交互，
        每次将历史信息添加到messages中
        """
        # 初始化messages
        prompt_task_ground_file = "prompt_UTS_task_ground_given.txt"

        prompt_task_ground_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), prompt_task_ground_file)

        with open(prompt_task_ground_path, 'r', encoding='utf-8') as f:
            prompt_task_ground = f.read()

        # print(prompt_task_ground)

        # 保存历史记录
        preds = []
        
        # 遍历所有base64图像并逐步推理
        # print(base64_image_list)
        # print(len(base64_image_list))
        for pred_0, base64_image in zip(preds_0, base64_image_list):
            data_uri = generate_data_uri(base64_image)
            old_x = pred_0["ele_loc"]["x"]
            old_y = pred_0["ele_loc"]["y"]
            pred_0["ele_loc"]["x"] = 0
            pred_0["ele_loc"]["y"] = 0
            # print(pred_0)
            pred_0_text = pred_0 if isinstance(pred_0, str) else json.dumps(pred_0, ensure_ascii=False)
            # print(data_uri)
            messages = [
                {
                    "role": "system",
                    "content": [{"type": "text", "text": prompt_task_ground}]
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": pred_0_text},
                        # 初始图像可以是第一张
                        {"type": "image_url", "image_url": {"url": data_uri}} 
                    ]
                }
            ]

            # 调用模型获取输出
            chat_completion = self.client.chat.completions.create(
                model="tgi",  # 需要根据实际模型调整
                messages=messages,
                top_p=None,
                temperature=0.0,
                max_tokens=400,
                stream=True
            )
            
            # 从模型的响应中提取内容
            # print(chat_completion)
            response = ""
            for message in chat_completion:
                response += message.choices[0].delta.content

            x, y = extract_ele_loc(response)
            print(x, y)
            if x==-1 or y==-1:
                pred_0["ele_loc"]["x"] = old_x
                pred_0["ele_loc"]["y"] = old_y
            else:
                pred_0["ele_loc"]["x"] = x
                pred_0["ele_loc"]["y"] = y
            if(pred_0==None):
                return None
            # # 输出模型返回内容，作为下一轮输入的历史记录
            preds.append(pred_0)
        
        # return preds
        return preds_0


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

