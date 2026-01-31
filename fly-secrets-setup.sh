#!/bin/bash
# Fly.io secrets setup script
# Run these commands to set up required environment variables

echo "Setting up Fly.io secrets for coco-backend-tyler..."
echo ""
echo "You need to run these commands with your actual values:"
echo ""
echo "# Required secrets:"
echo "flyctl secrets set DATABASE_URL='postgresql://neondb_owner:npg_EydhUz3wN8jC@ep-billowing-leaf-afk75rlp-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require' -a coco-backend-tyler"
echo "flyctl secrets set INGEST_SERVICE_TOKEN='06GuXL-3phwkuRZzS7_Ghvj17HGzhpg31fGYnA_y-bU' -a coco-backend-tyler"
echo "flyctl secrets set ADMIN_TOKEN='shrimpfriedrice' -a coco-backend-tyler"
echo "flyctl secrets set DASHBOARD_ORIGIN='http://localhost:8000' -a coco-backend-tyler"
echo ""
echo "# Optional secrets for R2 storage (audio uploads):"
echo "flyctl secrets set R2_ENDPOINT='https://f30d8c5fd96c155557b653c92d772b56.r2.cloudflarestorage.com' -a coco-backend-tyler"
echo "flyctl secrets set R2_ACCESS_KEY_ID='a88113fe2c83fc39b4fc3890705e3d9b' -a coco-backend-tyler"
echo "flyctl secrets set R2_SECRET_ACCESS_KEY='6a0912904684bcc760a7144abecbb48e6096e541e6f0f8515e39ec0224d99f31' -a coco-backend-tyler"
echo "flyctl secrets set R2_BUCKET_NAME='coco-audio-recordings' -a coco-backend-tyler"
echo ""
echo "# Check current secrets:"
echo "flyctl secrets list -a coco-backend-tyler"
