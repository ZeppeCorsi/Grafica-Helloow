"""Gera o logo da helloow em PNG 500x500 (fundo transparente fora do circulo).

Desenha direto com Pillow para ficar nitido, espelhando o helloow-logo.svg.
Rodar:  python gerar_logo_png.py
"""
from PIL import Image, ImageDraw, ImageFont

TAM = 500
PRETO = (30, 30, 30, 255)        # #1E1E1E
BRANCO = (255, 255, 255, 255)
AMARELO = (245, 179, 1, 255)     # #F5B301

img = Image.new("RGBA", (TAM, TAM), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# circulo de fundo
d.ellipse([0, 0, TAM - 1, TAM - 1], fill=PRETO)

# fontes (Arial do Windows)
fonte_main = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 118)
fonte_sub = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 33)

# --- wordmark "helloow" centralizado (helloo branco + w amarelo) ---
parte1, parte2 = "helloo", "w"
w1 = d.textlength(parte1, font=fonte_main)
w2 = d.textlength(parte2, font=fonte_main)
total = w1 + w2
x0 = (TAM - total) / 2
baseline = 300  # y da base do texto principal

d.text((x0, baseline), parte1, font=fonte_main, fill=BRANCO, anchor="ls")
d.text((x0 + w1, baseline), parte2, font=fonte_main, fill=AMARELO, anchor="ls")

# --- subtitulo "Industria Grafica" alinhado a direita do wordmark ---
borda_direita = x0 + total
d.text((borda_direita, baseline + 38), "Indústria Gráfica",
       font=fonte_sub, fill=BRANCO, anchor="rs")

img.save("helloow-logo.png")
print("Gerado: helloow-logo.png (500x500)")
