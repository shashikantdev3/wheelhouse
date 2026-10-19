FROM wheelhouse-lab-base
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends mariadb-server mariadb-client \
 && rm -rf /var/lib/apt/lists/* \
 && sed -i 's/^bind-address.*/bind-address = 0.0.0.0/' /etc/mysql/mariadb.conf.d/50-server.cnf
COPY seed.sql /opt/lab/seed.sql
RUN chmod 0600 /opt/lab/seed.sql
COPY lab-seed.service /etc/systemd/system/lab-seed.service
RUN systemctl enable lab-seed
COPY mysql-readonly.cnf /etc/wheelhouse/mysql-readonly.cnf
RUN chmod 0644 /etc/wheelhouse/mysql-readonly.cnf
