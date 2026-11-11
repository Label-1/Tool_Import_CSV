"""Generates original decorative PNG assets for the desktop space theme.
This file is a build-time convenience; Windows runtime only needs Tkinter.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter
import random, math

OUT=Path(__file__).resolve().parent/'assets'; OUT.mkdir(exist_ok=True)

def mix(a,b,t): return tuple(round(a[i]*(1-t)+b[i]*t) for i in range(3))
def radial(x,y,cx,cy,sx,sy): return math.exp(-(((x-cx)/sx)**2+((y-cy)/sy)**2))
def draw_scene(w,h,planet=True,seed=17):
    pixels=Image.new('RGB',(w,h)); pix=pixels.load()
    rng=random.Random(seed)
    for y in range(h):
        for x in range(w):
            t=y/max(1,h)
            base=mix((8,12,32),(22,15,59),t)
            n1=radial(x,y,w*.76,h*.78,w*.23,h*.83)
            n2=radial(x,y,w*.39,h*.1,w*.3,h*.65)
            n3=radial(x,y,w*.96,h*.15,w*.2,h*.6)
            pix[x,y]=(min(255,int(base[0]+n1*31+n2*7+n3*25)),min(255,int(base[1]+n1*13+n2*6+n3*6)),min(255,int(base[2]+n1*49+n2*29+n3*52)))
    im=pixels.convert('RGBA')
    stars=Image.new('RGBA',(w,h),(0,0,0,0)); sd=ImageDraw.Draw(stars,'RGBA')
    for i in range(round(w*h/1200)):
        x=rng.randrange(w); y=rng.randrange(h)
        r=rng.choices([0.6,0.8,1.2,1.8],[46,31,18,5])[0]
        hue=rng.choice([(188,216,255),(198,175,255),(255,218,244),(153,236,255)])
        alpha=rng.randrange(90,225)
        sd.ellipse((x-r,y-r,x+r,y+r), fill=(*hue,alpha))
        if r>=1.8:
            sd.line((x-5,y,x+5,y),fill=(*hue,90),width=1)
            sd.line((x,y-5,x,y+5),fill=(*hue,90),width=1)
    im=Image.alpha_composite(im,stars)
    if planet:
        # An original ringed planet on the right. Ring layers are handled by annular ellipses.
        cx,cy=w*.83,h*.70; R=h*.58
        shadow=Image.new('RGBA',(w,h),(0,0,0,0)); sh=ImageDraw.Draw(shadow,'RGBA')
        for k in range(23,0,-1):
            rr=R*(1+k/34)
            sh.ellipse((cx-rr,cy-rr,cx+rr,cy+rr),fill=(99,49,221,max(1,int(5*(24-k)/23))))
        im=Image.alpha_composite(im,shadow.filter(ImageFilter.GaussianBlur(8)))
        # behind ring ellipse
        rings=Image.new('RGBA',(w,h),(0,0,0,0)); rd=ImageDraw.Draw(rings,'RGBA')
        for j in range(18):
            rr=R*1.8 + j*2
            rd.ellipse((cx-rr,cy-rr*.32,cx+rr,cy+rr*.32),outline=(122+j*4,101,255,80-j*2),width=2)
        im=Image.alpha_composite(im,rings)
        planetim=Image.new('RGBA',(w,h),(0,0,0,0)); pd=ImageDraw.Draw(planetim,'RGBA')
        pd.ellipse((cx-R,cy-R,cx+R,cy+R),fill=(20,28,92,255))
        for j in range(34):
            rr=R*(1-j/44)
            # crescent illumination
            offs=j*.30
            pd.arc((cx-rr-offs,cy-rr,cx+rr-offs,cy+rr),start=215,end=355,fill=(95+j*3,58+j*2,170+j*2,max(40,210-j*5)),width=3)
        # thin rim
        pd.arc((cx-R,cy-R,cx+R,cy+R),start=187,end=345,fill=(166,147,255,210),width=4)
        im=Image.alpha_composite(im,planetim)
        # front rings
        ring2=Image.new('RGBA',(w,h),(0,0,0,0)); r2=ImageDraw.Draw(ring2,'RGBA')
        for j in range(8):
            rr=R*1.85+j*3
            r2.arc((cx-rr,cy-rr*.32,cx+rr,cy+rr*.32),start=3,end=177,fill=(132+j*4,135+j*2,255,210-j*11),width=2)
        im=Image.alpha_composite(im,ring2)
    return im.convert('RGB')

header=draw_scene(1850,160,True,18)
header.save(OUT/'space_header.png',optimize=True)
side=draw_scene(390,185,True,28)
side.save(OUT/'space_sidebar.png',optimize=True)
logo=Image.new('RGBA',(64,64),(0,0,0,0)); dl=ImageDraw.Draw(logo,'RGBA')
dl.ellipse((10,9,54,55),fill=(26,20,85,255),outline=(159,116,255,255),width=3)
dl.ellipse((3,25,61,44),outline=(111,223,255,255),width=3)
dl.rectangle((24,20,41,27),fill=(182,162,255,255))
dl.rectangle((24,29,41,36),fill=(114,117,252,255))
dl.rectangle((24,38,41,45),fill=(69,202,251,255))
logo.save(OUT/'app_icon.png')
print('Assets:',*[f'{p.name} {p.stat().st_size}' for p in OUT.iterdir()])
