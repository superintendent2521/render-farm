from renderfarm.security import LoginLimiter, hash_password, opaque_token, token_hash, verify_password


def test_password_and_token_hashing():
    encoded = hash_password("correct horse battery staple")
    assert verify_password(encoded, "correct horse battery staple")
    assert not verify_password(encoded, "wrong")
    token = opaque_token()
    assert token_hash(token) == token_hash(token)
    assert token_hash(token) != token_hash(opaque_token())


def test_login_limiter():
    limiter = LoginLimiter(attempts=2, window_seconds=60)
    assert limiter.allowed("client")
    limiter.fail("client")
    assert limiter.allowed("client")
    limiter.fail("client")
    assert not limiter.allowed("client")
    limiter.clear("client")
    assert limiter.allowed("client")
