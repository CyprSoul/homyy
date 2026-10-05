# ComfyUI → Open WebUI

Адмін → Зображення:

| Поле | Значення |
|---|---|
| Рушій | ComfyUI |
| URL ComfyUI | `http://host.docker.internal:8188` |
| ComfyUI Workflow | [`zimage_api.json`](zimage_api.json) |
| Модель | `z_image_turbo_bf16.safetensors` |
| Розмір | `1024x1024` |
| Кроки | `8` |

Вузли Workflow:

| Тип | Ключ | ID вузла |
|---|---|---|
| prompt | `text` | `67` |
| model | `unet_name` (не `ckpt_name`!) | `66` |
| width | `width` | `68` |
| height | `height` | `68` |
| steps | `steps` | `70` |
| seed | `seed` | `70` |
