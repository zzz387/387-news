"""A compact, deterministic home view of an immutable published overview."""
import re


def compact(page):
    page=page.replace('<body>','<body class="edition-compact">',1)
    page=re.sub(r'<div class="mast-top">.*?</div>','',page,count=1,flags=re.S)
    page=re.sub(r'<div class="motto">.*?</div>','',page,count=1,flags=re.S)
    page=re.sub(r'<section class="front-intro">.*?</section>','<h1 class="visually-hidden">Обзор номера</h1>',page,count=1,flags=re.S)
    return page


def homepage(overview,date):
    return compact(overview).replace('href="https://387.su/issues/'+date+'/"','href="https://387.su/"',1)
