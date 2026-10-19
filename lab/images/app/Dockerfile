FROM wheelhouse-lab-base
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends memcached \
 && rm -rf /var/lib/apt/lists/* \
 && sed -i 's/^-l .*/-l 127.0.0.1/' /etc/memcached.conf \
 && useradd --system --no-create-home orders
COPY orders_api.py /opt/orders/orders_api.py
COPY orders-api.service /etc/systemd/system/orders-api.service
RUN systemctl enable orders-api
