import gradio as gr
import json
import requests
import random
import websocket #NOTE: websocket-client (https://github.com/websocket-client/websocket-client)
import uuid
import urllib.request
import urllib.parse
from PIL import Image, ImageOps
import io
import os
from io import BytesIO


server_address = "127.0.0.1:8188"
client_id = str(uuid.uuid4())


def generate_random_seed():   # Generates a random seed for each run
    seed = random.randint(0, 2**32 - 1)  # Random integer between 0 and the maximum 32-bit value
    return seed

def queue_prompt(prompt):   # Kicks off the generation
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req =  urllib.request.Request("http://{}/prompt".format(server_address), data=data)
    return json.loads(urllib.request.urlopen(req).read())


def get_image(filename, subfolder, folder_type):
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen("http://{}/view?{}".format(server_address, url_values)) as response:
        return response.read()


def get_history(prompt_id):
    with urllib.request.urlopen("http://{}/history/{}".format(server_address, prompt_id)) as response:
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
                    break #Execution is done
        else:
            # If you want to be able to decode the binary stream for latent previews, here is how you can do it:
            # bytesIO = BytesIO(out[8:])
            # preview_image = Image.open(bytesIO) # This is your preview in PIL image format, store it in a global
            continue #previews are binary data

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


def pil_to_png(pil_image, file_name, directory):
    os.makedirs(directory, exist_ok=True)   # Ensure the directory exists
    file_name += ".png"     # Add png extension
    file_path = os.path.join(directory, file_name)
    pil_image.save(file_path, format='PNG')     # Save the png image
    return os.path.abspath(file_path)


def process_masks(mask_image_path):     # Add black background to masks 
    mask_image = Image.open(mask_image_path).convert("RGBA")
    mask_black_background = Image.new('RGBA', mask_image.size, (0, 0, 0, 255))    #Create a black background
    mask_black_background.paste(mask_image, (0, 0), mask_image)     #Composite the image onto the white background
    mask_black_background = mask_black_background.convert("RGB")    # Convert the image to RGB (removes alpha channel)
    mask_black_background.save(mask_image_path)    #Save the iamge
    return os.path.abspath(mask_image_path)


def generate_image(clothing_input, target_input):   # Main image generation workflow
    # Load workflow
    with open("clothes-transfer-api-v2.json") as workflow:
        prompt = json.load(workflow)

    prompt["424"]["inputs"]["seed"] = generate_random_seed()    # Set the seed
    print(prompt["424"]["inputs"]["seed"])
    
    input_image_directory = "C:\\Users\\amogh\\OneDrive\\Documents\\Dashtoon\\clothing-app\\input"

    # Get clothing image from Gradio
    clothing_image = clothing_input.get("background")
    clothing_image_png = pil_to_png(clothing_image, "clothing-image", input_image_directory)
    print(clothing_image_png)

    # Get clothing mask from Gradio
    clothing_mask = clothing_input.get("layers")[0]
    clothing_mask_png = pil_to_png(clothing_mask, "clothing-mask", input_image_directory) #saves the transparent mask as png
    process_masks(clothing_mask_png)    # process mask to remove transparency
    print(clothing_mask_png)

    # Get target image from Gradio
    target_image = target_input.get("background") 
    target_image_png = pil_to_png(target_image, "target-image", input_image_directory)
    print(target_image_png)

    # Get target mask from Gradio
    target_mask = target_input.get("layers")[0]
    target_mask_png = pil_to_png(target_mask, "target-mask", input_image_directory)
    process_masks(target_mask_png)      # process mask to remove transparency
    print(target_mask_png)


    # Pass user input images and masks from Gradio to Comfy
    prompt["422"]["inputs"]["image"] = clothing_image_png
    prompt["695"]["inputs"]["image"] = clothing_mask_png
    prompt["590"]["inputs"]["image"] = target_image_png
    prompt["696"]["inputs"]["image"] = target_mask_png


    # Connect to WebSocket and retrieve images
    ws = websocket.WebSocket()
    ws.connect(f"ws://{server_address}/ws?clientId={client_id}")
    images = get_images(ws, prompt)  # Get the dictionary of images
    ws.close()

    #If images are returned
    if images:
        final_image_data = images.get("581")[0]  # Get the raw bytes of final image from node 581
        # Convert raw bytes to a PIL Image
        pil_image = Image.open(BytesIO(final_image_data))
        return pil_image  # Return a PIL Image that Gradio can process
    else:
        raise ValueError("No images were generated.")


#Gradio interface
with gr.Blocks() as demo:
    gr.Markdown("""
        # DashTailor Clothing Transfer
        Transfer clothing from one image to another
        """)
    with gr.Row():
            with gr.Column():
                # Create image editors for both input images
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

                # Add instructions for users
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
    #Kick off image generation from Gradio
    generate_btn.click(
        fn=generate_image,
        inputs=[clothing_image, target_image],
        outputs=[output_image],
        show_progress=True
        )
    
demo.launch()
