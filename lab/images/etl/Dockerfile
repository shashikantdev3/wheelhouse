FROM wheelhouse-lab-base
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends mariadb-client \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --no-create-home etl
COPY orders_daily.sh /opt/etl/orders_daily.sh
COPY orders-daily.service orders-daily.timer /etc/systemd/system/
RUN chmod 0755 /opt/etl/orders_daily.sh && systemctl enable orders-daily.timer
