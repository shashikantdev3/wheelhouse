# Base for every lab host: Ubuntu with real systemd, OpenSSH and sudo.
# The lab runs systemd as PID 1 so agents meet the same systemctl and journalctl
# they will meet on client servers.
FROM public.ecr.aws/docker/library/ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends \
      systemd systemd-sysv dbus openssh-server sudo iproute2 iputils-ping procps \
      ca-certificates python3 \
 && rm -rf /var/lib/apt/lists/* \
 && rm -f /etc/ssh/ssh_host_* \
 && useradd --create-home --shell /bin/bash --groups systemd-journal wheelhouse \
 && passwd -l wheelhouse \
 && mkdir -p /home/wheelhouse/.ssh /etc/wheelhouse \
 && chown wheelhouse:wheelhouse /home/wheelhouse/.ssh && chmod 700 /home/wheelhouse/.ssh \
 && systemctl enable ssh \
 && systemctl mask systemd-logind getty@tty1 console-getty
COPY sshd-wheelhouse.conf /etc/ssh/sshd_config.d/10-wheelhouse.conf
COPY lab-keys /usr/local/sbin/lab-keys
COPY lab-keys.service /etc/systemd/system/lab-keys.service
RUN chmod 0755 /usr/local/sbin/lab-keys && systemctl enable lab-keys \
 && mkdir -p /etc/systemd/system/ssh.service.d \
 && printf '[Unit]\nRequires=lab-keys.service\nAfter=lab-keys.service\n' > /etc/systemd/system/ssh.service.d/lab.conf
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
