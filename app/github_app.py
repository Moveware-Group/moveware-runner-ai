"""
GitHub App Authentication

Handles authentication and token management for GitHub App installations.
"""
import os
import time
from typing import Optional
from datetime import datetime, timedelta
import jwt
import requests
from dataclasses import dataclass


@dataclass
class GitHubAppConfig:
    """GitHub App configuration."""
    app_id: str
    private_key_path: str
    installation_id: Optional[str] = None


@dataclass
class InstallationToken:
    """GitHub App installation access token."""
    token: str
    expires_at: datetime
    
    def is_expired(self) -> bool:
        """Check if token is expired (with 5 min buffer)."""
        return datetime.now() >= self.expires_at - timedelta(minutes=5)


class GitHubAppAuth:
    """
    GitHub App authentication manager.
    
    Handles JWT generation and installation token management.
    """
    
    def __init__(self, config: GitHubAppConfig):
        """
        Initialize GitHub App authentication.
        
        Args:
            config: GitHub App configuration
        """
        self.config = config
        self._installation_token: Optional[InstallationToken] = None
        
        # Load private key
        if not os.path.exists(config.private_key_path):
            raise FileNotFoundError(f"Private key not found: {config.private_key_path}")
        
        with open(config.private_key_path, 'r') as f:
            self.private_key = f.read()
    
    def _generate_jwt(self) -> str:
        """
        Generate a JWT for GitHub App authentication.
        
        Returns:
            JWT token string
        """
        now = int(time.time())
        
        payload = {
            'iat': now - 60,  # Issued at (60 seconds ago to account for clock drift)
            'exp': now + 600,  # Expires in 10 minutes
            'iss': self.config.app_id  # Issuer (app ID)
        }
        
        return jwt.encode(payload, self.private_key, algorithm='RS256')
    
    def _get_installation_token(self) -> InstallationToken:
        """
        Get an installation access token from GitHub.
        
        Returns:
            Installation token
        """
        jwt_token = self._generate_jwt()
        
        # Determine installation ID
        installation_id = self.config.installation_id
        
        if not installation_id:
            # Get the first installation for this app
            headers = {
                'Authorization': f'Bearer {jwt_token}',
                'Accept': 'application/vnd.github.v3+json'
            }
            
            response = requests.get(
                'https://api.github.com/app/installations',
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            
            installations = response.json()
            if not installations:
                raise ValueError("No installations found for this GitHub App")
            
            installation_id = str(installations[0]['id'])
            print(f"Auto-detected installation ID: {installation_id}")
        
        # Get installation token
        headers = {
            'Authorization': f'Bearer {jwt_token}',
            'Accept': 'application/vnd.github.v3+json'
        }
        
        response = requests.post(
            f'https://api.github.com/app/installations/{installation_id}/access_tokens',
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        
        data = response.json()
        
        return InstallationToken(
            token=data['token'],
            expires_at=datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
        )
    
    def get_token(self) -> str:
        """
        Get a valid installation access token.
        
        Automatically refreshes if expired.
        
        Returns:
            Access token string
        """
        if not self._installation_token or self._installation_token.is_expired():
            print("Refreshing GitHub App installation token...")
            self._installation_token = self._get_installation_token()
        
        return self._installation_token.token
    
    def get_auth_header(self) -> dict:
        """
        Get authorization header for GitHub API requests.
        
        Returns:
            Dict with Authorization header
        """
        return {
            'Authorization': f'token {self.get_token()}',
            'Accept': 'application/vnd.github.v3+json'
        }


# Global instance (lazy-loaded)
_github_app_auth: Optional[GitHubAppAuth] = None


def get_github_app_auth() -> Optional[GitHubAppAuth]:
    """
    Get or create the global GitHub App auth instance.
    
    Returns None if not configured (falls back to PAT).
    
    Returns:
        GitHubAppAuth instance or None
    """
    global _github_app_auth
    
    if _github_app_auth is not None:
        return _github_app_auth
    
    # Check if GitHub App is configured
    app_id = os.getenv('GITHUB_APP_ID')
    private_key_path = os.getenv('GITHUB_APP_PRIVATE_KEY_PATH')
    
    if not app_id or not private_key_path:
        # Not configured, will fall back to PAT
        return None
    
    try:
        config = GitHubAppConfig(
            app_id=app_id,
            private_key_path=private_key_path,
            installation_id=os.getenv('GITHUB_APP_INSTALLATION_ID')
        )
        
        _github_app_auth = GitHubAppAuth(config)
        print(f"✓ GitHub App authentication initialized (App ID: {app_id})")
        
        return _github_app_auth
        
    except Exception as e:
        print(f"⚠ Failed to initialize GitHub App auth: {e}")
        print("  Falling back to PAT authentication")
        return None


def get_github_token() -> str:
    """
    Get GitHub authentication token.
    
    Tries GitHub App first, falls back to PAT (GH_TOKEN).
    
    Returns:
        GitHub token string
    """
    # Try GitHub App first
    app_auth = get_github_app_auth()
    if app_auth:
        return app_auth.get_token()
    
    # Fall back to PAT
    token = os.getenv('GH_TOKEN', '')
    if not token:
        raise ValueError("No GitHub authentication configured (GH_TOKEN or GitHub App)")
    
    return token
