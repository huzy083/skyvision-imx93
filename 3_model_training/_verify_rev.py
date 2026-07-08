from docx import Document
import os
base = "/home/shing/uav_ground_station/"
src = base + "第二十一届研电赛技术论文_大模型智能体电力巡检_规范版(1).docx"
out = base + "第二十一届研电赛技术论文_大模型智能体电力巡检_规范版_修订.docx"
print("原件存在:", os.path.exists(src), os.path.getsize(src) if os.path.exists(src) else "-")
print("修订存在:", os.path.exists(out), os.path.getsize(out) if os.path.exists(out) else "-")
if os.path.exists(out):
    d = Document(out)
    for i in (60, 61, 62, 63, 76, 77):
        print(f"[{i}] {d.paragraphs[i].text[:60]}")
