curl https://api.github.com/repos/Antares0982/RabbitMQInterface/contents/rabbitmq_interface.py | jq -r ".content" | base64 --decode > rabbitmq_interface.py
