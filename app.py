import gradio as gr
import json
import requests
import random
import websocket
import uuid
import urllib.request
import urllib.parse
from PIL import Image, ImageOps
import io
import os
from io import BytesIO

server_address = "100.65.0.5:60000"
client_id = str(uuid.uuid4())

def generate_random_seed():
    seed = random.randint(0, 2**32 - 1)
    return seed

def upload_image_to_comfy(pil_image, image_type):
    # Generate a unique UUID for this image
    unique_id = str(uuid.uuid4())
    image_name = f"{image_type}_{unique_id}"
    
    # Convert PIL image to bytes
    buffered = BytesIO()
    pil_image.save(buffered, format="PNG")
    image_bytes = buffered.getvalue()

    # Prepare the multipart form data
    files = {
        'image': (image_name + '.png', image_bytes, 'image/png')
    }
    
    try:
        response = requests.post(f"http://{server_address}/upload/image", files=files)
        response.raise_for_status()
        uploaded_name = response.json()["name"]
        print(f"Uploaded {image_type} with ID {unique_id}: {uploaded_name}")  # Debug print
        return uploaded_name
    except Exception as e:
        print(f"Upload failed for {image_type} with ID {unique_id}: {str(e)}")
        raise

def queue_prompt(prompt):
    try:
        p = {"prompt": prompt, "client_id": client_id}
        data = json.dumps(p).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        req = urllib.request.Request(
            f"http://{server_address}/prompt",
            data=data,
            headers=headers,
            method='POST'
        )
        response = urllib.request.urlopen(req)
        return json.loads(response.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.reason}")
        print(f"Response: {e.read().decode()}")
        raise

def get_image(filename, subfolder, folder_type):
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen(f"http://{server_address}/view?{url_values}") as response:
        return response.read()

def get_history(prompt_id):
    with urllib.request.urlopen(f"http://{server_address}/history/{prompt_id}") as response:
        return json.loads(response.read())

def get_images(ws, prompt):
    prompt_id = queue_prompt(prompt)['prompt_id']
    output_images = {}
    while True:
        out = ws.recv()
        if isinstance(out, str):
            message = json.loads(out)
            if message['type'] == 'executing':
                data = message['data']
                if data['node'] is None and data['prompt_id'] == prompt_id:
                    break
        else:
            continue

    history = get_history(prompt_id)[prompt_id]
    for node_id in history['outputs']:
        node_output = history['outputs'][node_id]
        images_output = []
        if 'images' in node_output:
            for image in node_output['images']:
                image_data = get_image(image['filename'], image['subfolder'], image['type'])
                images_output.append(image_data)
        output_images[node_id] = images_output
    print("Output images ready")
    return output_images

# def process_mask(mask_image, save_path):
#     # Convert to RGBA if not already
#     if mask_image.mode != 'RGBA':
#         mask_image = mask_image.convert('RGBA')
    
#     # Create black background
#     mask_black_background = Image.new('RGBA', mask_image.size, (0, 0, 0, 255))
    
#     # Composite the image onto the black background using alpha channel
#     mask_black_background.paste(mask_image, (0, 0), mask_image)
    
#     # Convert to RGB and save
#     mask_black_background = mask_black_background.convert('RGB')
#     mask_black_background.save(save_path)
#     return save_path

def convert_mask_to_rgb(mask_image):
    # Create a black RGB background
    rgb_mask = Image.new('RGB', mask_image.size, (0, 0, 0))
    
    # Convert any non-transparent pixels to white
    for x in range(mask_image.size[0]):
        for y in range(mask_image.size[1]):
            if mask_image.getpixel((x, y))[3] > 0:  # If pixel has any opacity
                rgb_mask.putpixel((x, y), (255, 255, 255))
    
    return rgb_mask

def generate_image(clothing_input, target_input):
    # Load workflow
    with open("clothes-transfer-api-v2.json") as workflow:
        prompt = json.load(workflow)

    prompt["102"]["inputs"]["seed"] = generate_random_seed()
    print(prompt["102"]["inputs"]["seed"])

    # Get images and their masks from Gradio
    clothing_image = clothing_input.get("background")
    clothing_mask = clothing_input.get("layers")[0]  # Get the layer
    target_image = target_input.get("background")
    target_mask = target_input.get("layers")[0]     # Get the layer

    # Convert masks to RGB with white strokes on black background
    clothing_mask = convert_mask_to_rgb(clothing_mask)
    target_mask = convert_mask_to_rgb(target_mask)

    # Create temp directory if it doesn't exist
    os.makedirs("temp", exist_ok=True)

    # Save all images locally with unique IDs
    clothing_image_path = f"temp/clothing_image_{uuid.uuid4()}.png"
    clothing_mask_path = f"temp/clothing_mask_{uuid.uuid4()}.png"
    target_image_path = f"temp/target_image_{uuid.uuid4()}.png"
    target_mask_path = f"temp/target_mask_{uuid.uuid4()}.png"

    # Save everything as PNG images
    clothing_image.save(clothing_image_path, "PNG")
    clothing_mask.save(clothing_mask_path, "PNG")
    target_image.save(target_image_path, "PNG")
    target_mask.save(target_mask_path, "PNG")

    print(f"\nSaved images locally:")
    print(f"Clothing image: {clothing_image_path}")
    print(f"Clothing mask: {clothing_mask_path}")
    print(f"Target image: {target_image_path}")
    print(f"Target mask: {target_mask_path}")

    # Upload saved images to ComfyUI server
    clothing_image_name = upload_image_to_comfy(Image.open(clothing_image_path), "clothing_image")
    clothing_mask_name = upload_image_to_comfy(Image.open(clothing_mask_path), "clothing_mask")
    target_image_name = upload_image_to_comfy(Image.open(target_image_path), "target_image")
    target_mask_name = upload_image_to_comfy(Image.open(target_mask_path), "target_mask")

    # Update the prompt with server-side image paths
    prompt["422"]["inputs"]["image"] = clothing_image_name
    prompt["695"]["inputs"]["image"] = clothing_mask_name
    prompt["590"]["inputs"]["image"] = target_image_name
    prompt["696"]["inputs"]["image"] = target_mask_name

    # Update GPT model to valid value
    prompt["692"]["inputs"]["model"] = "gpt-4o"

    print("\nFinal prompt image paths:")
    print(f"Clothing: {prompt['422']['inputs']['image']}")
    print(f"Clothing mask: {prompt['695']['inputs']['image']}")
    print(f"Target: {prompt['590']['inputs']['image']}")
    print(f"Target mask: {prompt['696']['inputs']['image']}")

    # Connect to WebSocket and retrieve images
    ws = websocket.WebSocket()
    ws.connect(f"ws://{server_address}/ws?clientId={client_id}")
    images = get_images(ws, prompt)
    ws.close()

    if images:
        final_image_data = images.get("581")[0]
        pil_image = Image.open(BytesIO(final_image_data))
        return pil_image
    else:
        raise ValueError("No images were generated.")

# Gradio interface
with gr.Blocks() as demo:
    gr.Markdown("""
        # DashTailor Clothing Transfer
        Transfer clothing from one image to another
        """)
    with gr.Row():
        with gr.Column():
            clothing_image = gr.ImageEditor(
                label="Source Clothing Image",
                type="pil",
                sources=["upload"],
                interactive=True,
                brush=gr.Brush(colors=["#FFFFFF"], color_mode="fixed"),
                width=1024,
                height=800
            )
            
            target_image = gr.ImageEditor(
                label="Target Person Image",
                type="pil",
                sources=["upload"],
                interactive=True,
                brush=gr.Brush(colors=["#FFFFFF"], color_mode="fixed"),
                width=1024,
                height=800
            )
            
            generate_btn = gr.Button("Generate", variant="primary")

        with gr.Column():
            output_image = gr.Image(
                label="Generated Result",
                width=1024,
                height=800
            )

            gr.Markdown("""
            ## Instructions:
            1. Upload the clothing image and draw a mask:
            - Click on 'Source Clothing Image' and select your source clothing image
            - Use the brush tool to paint over the clothing area
            - The masked area will be transferred 
                    
            2. Upload the target character image and mask the target area:
            - Click 'Source Clothing Image' and select your target character image
            - Use the brush tool to paint the area where you want the clothing on the character
            - This guides the AI in placement         
                    
            3. Click 'Generate' to start the clothes transfer process
            
            ## Tips:
            - If you want to change only the upper garment of the character, mask only the upper garment in both images 
            - Use a smaller brush size for precise masking
            """)

    generate_btn.click(
        fn=generate_image,
        inputs=[clothing_image, target_image],
        outputs=[output_image],
        show_progress=True
    )

demo.launch()