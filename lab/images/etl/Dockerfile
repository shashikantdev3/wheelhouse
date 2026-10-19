FROM wheelhouse-lab-base
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends mariadb-client \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --no-create-home etl
COPY orders_daily.sh /opt/etl/orders_daily.sh
COPY orders-daily.service orders-daily.timer /etc/systemd/system/
COPY etl.cnf /etc/etl/etl.cnf
RUN chmod 0755 /opt/etl/orders_daily.sh && chown root:etl /etc/etl/etl.cnf && chmod 0640 /etc/etl/etl.cnf \
 && systemctl enable orders-daily.timer
