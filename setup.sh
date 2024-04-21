curl https://api.github.com/repos/Antares0982/PikaInterface/contents/pika_interface.py | jq -r ".content" | base64 --decode > pika_interface.py
