# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
#
# The weblogs demo's web shop (app.py), served by uvicorn behind the demo's nginx.
FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.115.6 uvicorn==0.32.1 "psycopg[binary]==3.2.3"
WORKDIR /app
COPY app.py ./
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
