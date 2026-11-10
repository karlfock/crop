cd <folder-with-images>

~/dev/crop/rata.sh            # alla bilder i mappen

~/dev/crop/rata.sh --pdf      # samma, plus en A4-PDF per bild (bilden till vänster, högra halvan tom att skriva på)

~/dev/crop/rata.sh --dubbel   # A4-PDF med samma bild på båda halvorna – skriv ut och klipp itu till två kort

~/dev/crop/rata.sh bild.jpg --edit # öppnar bild-editor.


Första gången skapar scriptet en .venv bredvid sig självt och installerar OpenCV, Pillow, NumPy och pillow-heif, så att HEIC-bilder också fungerar. Det tar någon minut, sedan går det direkt. Utan filnamn tar det alla jpg-, png- och heic-bilder i mappen och hoppar över de _rak.jpg som redan är skapade.