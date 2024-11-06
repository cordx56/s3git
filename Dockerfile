FROM amazonlinux:2023 AS git

WORKDIR /git

RUN yum install -y git
RUN mkdir -p /var/task/lib && \
    ldd /usr/bin/git | awk 'NF == 4 { system("cp " $3 " /var/task/lib/") }' && \
    ldd /usr/libexec/git-core/git-remote-http | awk 'NF == 4 { system("cp " $3 " /var/task/lib/") }' && \
    ldd /usr/libexec/git-core/git-remote-https | awk 'NF == 4 { system("cp " $3 " /var/task/lib/") }'


FROM public.ecr.aws/lambda/python:3.12

ENV PATH ${LAMBDA_TASK_ROOT}/bin:$PATH

# copy git
COPY --from=git /usr/bin/git ${LAMBDA_TASK_ROOT}/bin/
COPY --from=git /usr/libexec/git-core/git-remote-https ${LAMBDA_TASK_ROOT}/bin/
COPY --from=git /usr/libexec/git-core/git-remote-http ${LAMBDA_TASK_ROOT}/bin/
COPY --from=git /var/task/lib ${LAMBDA_TASK_ROOT}/lib

RUN git config --global --add safe.directory /tmp/vault

COPY requirements.lock ${LAMBDA_TASK_ROOT}
COPY pyproject.toml ${LAMBDA_TASK_ROOT}
RUN pip install -r requirements.lock

COPY src/handler.py ${LAMBDA_TASK_ROOT}

CMD ["handler.handler"]
