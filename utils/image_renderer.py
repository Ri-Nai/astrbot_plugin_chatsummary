import os
import markdown
from jinja2 import Template
from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration
import fitz  # PyMuPDF
from PIL import Image, ImageOps
import io
from datetime import datetime
import asyncio

try:
    from astrbot.api import html_renderer
except ImportError:
    html_renderer = None

class ImageRenderer:
    def __init__(self, template_name: str):
        """
        Initialize the ImageRenderer.
        
        Args:
            template_name (str): The name of the template registered in AstrBot's html_renderer.
        """
        self.template_name = template_name
        self.template_content = None
        self.base_url = os.getcwd()
        self.jinja_template = None

    async def _load_template(self):
        if self.jinja_template:
            return

        if not self.template_name:
             raise ValueError("template_name must be provided.")

        if html_renderer is None:
            raise RuntimeError("astrbot.api is not available, cannot load template by name.")
            
        # Fetch template content from AstrBot's registry
        content = html_renderer.network_strategy.get_template(self.template_name)
        if asyncio.iscoroutine(content):
            content = await content
        self.template_content = content
        
        if not self.template_content:
             raise ValueError(f"Could not load template content for name: {self.template_name}")

        # Adapt template if it's the original one (with JS injection)
        if '<article id="content"></article>' in self.template_content:
             self.template_content = self.template_content.replace(
                '<article id="content"></article>', 
                '<article id="content">{{ content }}</article>'
            )
        
        # Remove marked.js script if present to avoid confusion (though WeasyPrint ignores it)
        if '<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js">' in self.template_content:
             self.template_content = self.template_content.split('<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js">')[0] + "</body></html>"

        # Ensure CSS @page margin is 0 for better stitching
        # And inject Chinese font support
        extra_css = """
    @page {
      margin: 0;
    }
    body {
      font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "WenQuanYi Micro Hei", "Noto Sans CJK SC", sans-serif !important;
    }
    """
        if '</style>' in self.template_content:
             self.template_content = self.template_content.replace('</style>', f'{extra_css}\n</style>')
        elif '<style>' in self.template_content:
             self.template_content = self.template_content.replace('<style>', f'<style>\n{extra_css}\n')
        else:
             # Inject style if missing
             self.template_content = self.template_content.replace('</head>', f'<style>\n{extra_css}\n</style>\n</head>')

        self.jinja_template = Template(self.template_content)

    def render_markdown_to_image(self, markdown_text, output_path):
        """
        Render Markdown text to an image file.
        
        Args:
            markdown_text (str): The Markdown content to render.
            output_path (str): The path to save the generated image (e.g., 'output.png').
        """
        if not self.jinja_template:
             raise RuntimeError("Template not loaded. Call render() first.")

        # 1. Convert Markdown to HTML
        # 'extra' supports tables, 'codehilite' supports code highlighting
        html_body = markdown.markdown(markdown_text, extensions=['extra', 'codehilite'])

        # 2. Render HTML with Jinja2 template
        full_html = self.jinja_template.render(content=html_body)

        # 3. Generate PDF using WeasyPrint
        font_config = FontConfiguration()
        html = HTML(string=full_html, base_url=self.base_url)
        pdf_bytes = html.write_pdf(font_config=font_config)

        # 4. Convert PDF to Image using PyMuPDF (fitz) and Stitch/Crop
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        images = []
        for page in doc:
            # matrix=fitz.Matrix(2, 2) is equivalent to zoom=2 (higher resolution)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            
            # Convert to PIL Image
            mode = "RGB" if pix.n == 3 else "RGBA"
            img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
            images.append(img)
        
        doc.close()
        
        if not images:
            raise RuntimeError("Failed to generate any pages from PDF.")

        # 5. Stitch images vertically
        total_width = max(img.width for img in images)
        total_height = sum(img.height for img in images)
        
        stitched_image = Image.new('RGB', (total_width, total_height), (255, 255, 255))
        
        y_offset = 0
        for img in images:
            x_offset = (total_width - img.width) // 2
            stitched_image.paste(img, (x_offset, y_offset))
            y_offset += img.height
            
        # 6. Crop whitespace
        inverted_image = ImageOps.invert(stitched_image.convert('RGB'))
        bbox = inverted_image.getbbox()
        
        if bbox:
            padding = 20
            crop_bottom = min(total_height, bbox[3] + padding)
            crop_box = (0, 0, total_width, crop_bottom)
            final_image = stitched_image.crop(crop_box)
        else:
            final_image = stitched_image

        # 7. Save
        final_image.save(output_path)
        return output_path

    async def render(self, markdown_text: str, group_id: str = "default") -> str:
        """
        Render Markdown text to an image file and return the file URI.
        Automatically handles output path generation.
        
        Args:
            markdown_text (str): The Markdown content to render.
            group_id (str): Used for generating the filename.
            
        Returns:
            str: The file URI of the generated image.
        """
        await self._load_template()
        
        output_dir = os.path.join(os.getcwd(), "data", "astrbot_plugin_chatsummary", "images")
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = int(datetime.now().timestamp())
        output_filename = f"summary_{group_id}_{timestamp}.png"
        output_path = os.path.join(output_dir, output_filename)
        
        self.render_markdown_to_image(markdown_text, output_path)
        
        return f"file://{os.path.abspath(output_path)}"
