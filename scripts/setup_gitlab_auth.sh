#!/bin/bash
# Setup GitLab authentication for Code Atlas

set -e

echo "🔐 Setting up GitLab Authentication..."
echo ""

# Check if SSH keys exist
SSH_KEY="$HOME/.ssh/id_rsa"
SSH_KEY_PUB="$HOME/.ssh/id_rsa.pub"

if [ ! -f "$SSH_KEY" ]; then
    echo "⚠️  SSH key not found. Generating new SSH key..."
    read -p "Enter your GitLab email: " GITLAB_EMAIL
    ssh-keygen -t rsa -b 4096 -C "$GITLAB_EMAIL" -f "$SSH_KEY" -N ""
    echo "✅ SSH key generated"
else
    echo "✅ SSH key found: $SSH_KEY"
fi

# Display public key
echo ""
echo "📋 Your SSH Public Key:"
echo "---"
cat "$SSH_KEY_PUB"
echo "---"
echo ""

echo "📝 Next steps:"
echo "1. Copy the public key above"
echo "2. Go to GitLab: https://gitlab.com/-/profile/keys"
echo "3. Click 'Add new key'"
echo "4. Paste the public key"
echo "5. Click 'Add key'"
echo ""

read -p "Have you added the SSH key to GitLab? (y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "⚠️  Please add the SSH key to GitLab and run this script again"
    exit 0
fi

# Test SSH connection
echo ""
echo "🧪 Testing SSH connection to GitLab..."
if ssh -T git@gitlab.com 2>&1 | grep -q "Welcome to GitLab"; then
    echo "✅ SSH connection successful!"
else
    echo "⚠️  SSH connection test failed, but this might be normal"
    echo "   (GitLab may show a warning message)"
fi

# Convert HTTPS remotes to SSH
echo ""
echo "🔄 Converting HTTPS remotes to SSH..."
echo ""

REPO_BASE="/path/to/your/repos"
REPOS=(
    "my-service"
)

for repo in "${REPOS[@]}"; do
    repo_path="$REPO_BASE/$repo"
    if [ -d "$repo_path" ]; then
        cd "$repo_path"
        current_remote=$(git remote get-url origin 2>/dev/null || echo "")
        
        if [[ "$current_remote" == *"https://gitlab.com"* ]]; then
            # Extract org and repo name
            org_repo=$(echo "$current_remote" | sed 's|https://gitlab.com/||' | sed 's|\.git||')
            ssh_url="git@gitlab.com:$org_repo.git"
            
            echo "Converting $repo:"
            echo "  From: $current_remote"
            echo "  To:   $ssh_url"
            
            git remote set-url origin "$ssh_url"
            echo "  ✅ Converted"
        else
            echo "$repo: Already using SSH or not a GitLab repo"
        fi
    else
        echo "$repo: Directory not found"
    fi
done

echo ""
echo "✅ GitLab authentication setup complete!"
echo ""
echo "📋 Test a repository:"
echo "   cd /path/to/your/repos/my-service"
echo "   git fetch origin"
echo ""
