---
name: nodejs-api-dev
description: Node.js REST API development with Express, authentication, middleware, database integration, and error handling. Use when building Node.js APIs, Express servers, REST endpoints, or when the user mentions backend API development, Node.js servers, or Express.
---

# Node.js API Developer

## Project Structure

```
src/
├── routes/           # Route handlers
│   ├── auth.js
│   └── users.js
├── controllers/      # Business logic
│   └── userController.js
├── middleware/       # Custom middleware
│   ├── auth.js
│   ├── validation.js
│   └── errorHandler.js
├── models/          # Data models
│   └── User.js
├── services/        # External services
│   └── emailService.js
├── utils/           # Utilities
│   └── logger.js
├── config/          # Configuration
│   └── database.js
└── app.js           # Express app setup
```

## Express App Setup

```javascript
// app.js
const express = require('express')
const helmet = require('helmet')
const cors = require('cors')
const morgan = require('morgan')
const rateLimit = require('express-rate-limit')

const app = express()

// Security middleware
app.use(helmet())
app.use(cors({
  origin: process.env.ALLOWED_ORIGINS?.split(',') || '*',
  credentials: true
}))

// Rate limiting
const limiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 100, // Limit each IP to 100 requests per windowMs
  message: 'Too many requests from this IP'
})
app.use('/api/', limiter)

// Body parsing
app.use(express.json({ limit: '10mb' }))
app.use(express.urlencoded({ extended: true, limit: '10mb' }))

// Logging
app.use(morgan('combined'))

// Routes
app.use('/api/auth', require('./routes/auth'))
app.use('/api/users', require('./routes/users'))

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date() })
})

// Error handling (must be last)
app.use(require('./middleware/errorHandler'))

module.exports = app
```

## RESTful Route Patterns

```javascript
// routes/users.js
const express = require('express')
const router = express.Router()
const userController = require('../controllers/userController')
const { authenticate } = require('../middleware/auth')
const { validate } = require('../middleware/validation')
const { userSchema } = require('../schemas/user')

// Public routes
router.get('/', userController.list)
router.get('/:id', userController.getById)

// Protected routes
router.use(authenticate)
router.post('/', validate(userSchema), userController.create)
router.put('/:id', validate(userSchema), userController.update)
router.delete('/:id', userController.delete)

module.exports = router
```

## Controller Pattern

```javascript
// controllers/userController.js
const User = require('../models/User')
const { AppError } = require('../utils/errors')

exports.list = async (req, res, next) => {
  try {
    const { page = 1, limit = 10, search } = req.query
    
    const query = search 
      ? { name: { $regex: search, $options: 'i' } }
      : {}
    
    const users = await User.find(query)
      .limit(limit * 1)
      .skip((page - 1) * limit)
      .select('-password')
      .lean()
    
    const count = await User.countDocuments(query)
    
    res.json({
      users,
      totalPages: Math.ceil(count / limit),
      currentPage: page,
      total: count
    })
  } catch (error) {
    next(error)
  }
}

exports.getById = async (req, res, next) => {
  try {
    const user = await User.findById(req.params.id).select('-password')
    
    if (!user) {
      throw new AppError('User not found', 404)
    }
    
    res.json(user)
  } catch (error) {
    next(error)
  }
}

exports.create = async (req, res, next) => {
  try {
    const user = await User.create(req.body)
    
    res.status(201).json({
      message: 'User created successfully',
      user: { id: user._id, email: user.email }
    })
  } catch (error) {
    next(error)
  }
}

exports.update = async (req, res, next) => {
  try {
    const user = await User.findByIdAndUpdate(
      req.params.id,
      req.body,
      { new: true, runValidators: true }
    ).select('-password')
    
    if (!user) {
      throw new AppError('User not found', 404)
    }
    
    res.json({ message: 'User updated successfully', user })
  } catch (error) {
    next(error)
  }
}

exports.delete = async (req, res, next) => {
  try {
    const user = await User.findByIdAndDelete(req.params.id)
    
    if (!user) {
      throw new AppError('User not found', 404)
    }
    
    res.json({ message: 'User deleted successfully' })
  } catch (error) {
    next(error)
  }
}
```

## Authentication Middleware

```javascript
// middleware/auth.js
const jwt = require('jsonwebtoken')
const { AppError } = require('../utils/errors')

exports.authenticate = async (req, res, next) => {
  try {
    // Get token from header
    const token = req.headers.authorization?.replace('Bearer ', '')
    
    if (!token) {
      throw new AppError('No token provided', 401)
    }
    
    // Verify token
    const decoded = jwt.verify(token, process.env.JWT_SECRET)
    
    // Attach user to request
    req.user = decoded
    next()
  } catch (error) {
    if (error.name === 'JsonWebTokenError') {
      next(new AppError('Invalid token', 401))
    } else if (error.name === 'TokenExpiredError') {
      next(new AppError('Token expired', 401))
    } else {
      next(error)
    }
  }
}

exports.authorize = (...roles) => {
  return (req, res, next) => {
    if (!roles.includes(req.user.role)) {
      return next(new AppError('Insufficient permissions', 403))
    }
    next()
  }
}
```

## Validation Middleware

```javascript
// middleware/validation.js
const Joi = require('joi')
const { AppError } = require('../utils/errors')

exports.validate = (schema) => {
  return (req, res, next) => {
    const { error } = schema.validate(req.body, {
      abortEarly: false,
      stripUnknown: true
    })
    
    if (error) {
      const errors = error.details.map(detail => ({
        field: detail.path.join('.'),
        message: detail.message
      }))
      
      return next(new AppError('Validation failed', 400, errors))
    }
    
    next()
  }
}

// schemas/user.js
const Joi = require('joi')

exports.userSchema = Joi.object({
  name: Joi.string().min(2).max(50).required(),
  email: Joi.string().email().required(),
  password: Joi.string().min(8).required(),
  role: Joi.string().valid('user', 'admin').default('user')
})
```

## Error Handling

```javascript
// utils/errors.js
class AppError extends Error {
  constructor(message, statusCode = 500, errors = null) {
    super(message)
    this.statusCode = statusCode
    this.status = `${statusCode}`.startsWith('4') ? 'fail' : 'error'
    this.isOperational = true
    this.errors = errors
    Error.captureStackTrace(this, this.constructor)
  }
}

module.exports = { AppError }

// middleware/errorHandler.js
const { AppError } = require('../utils/errors')

module.exports = (err, req, res, next) => {
  err.statusCode = err.statusCode || 500
  err.status = err.status || 'error'
  
  // Log error
  console.error('Error:', {
    message: err.message,
    stack: err.stack,
    statusCode: err.statusCode,
    url: req.originalUrl,
    method: req.method
  })
  
  // Development mode
  if (process.env.NODE_ENV === 'development') {
    return res.status(err.statusCode).json({
      status: err.status,
      message: err.message,
      errors: err.errors,
      stack: err.stack
    })
  }
  
  // Production mode
  if (err.isOperational) {
    return res.status(err.statusCode).json({
      status: err.status,
      message: err.message,
      errors: err.errors
    })
  }
  
  // Programming or unknown errors
  res.status(500).json({
    status: 'error',
    message: 'Something went wrong'
  })
}
```

## Database Connection

```javascript
// config/database.js
const mongoose = require('mongoose')

const connectDB = async () => {
  try {
    const options = {
      useNewUrlParser: true,
      useUnifiedTopology: true,
      maxPoolSize: 10,
      serverSelectionTimeoutMS: 5000,
      socketTimeoutMS: 45000,
    }
    
    await mongoose.connect(process.env.MONGODB_URI, options)
    
    console.log('MongoDB connected successfully')
    
    mongoose.connection.on('error', (err) => {
      console.error('MongoDB connection error:', err)
    })
    
    mongoose.connection.on('disconnected', () => {
      console.warn('MongoDB disconnected')
    })
  } catch (error) {
    console.error('MongoDB connection failed:', error)
    process.exit(1)
  }
}

module.exports = connectDB
```

## Async Handler Wrapper

```javascript
// utils/asyncHandler.js
// Alternative to try-catch in every controller
module.exports = (fn) => (req, res, next) => {
  Promise.resolve(fn(req, res, next)).catch(next)
}

// Usage
const asyncHandler = require('../utils/asyncHandler')

exports.getUser = asyncHandler(async (req, res) => {
  const user = await User.findById(req.params.id)
  if (!user) throw new AppError('User not found', 404)
  res.json(user)
})
```

## Environment Configuration

```javascript
// config/env.js
const dotenv = require('dotenv')
const path = require('path')

dotenv.config({ path: path.resolve(__dirname, '../.env') })

const requiredEnvVars = [
  'NODE_ENV',
  'PORT',
  'MONGODB_URI',
  'JWT_SECRET'
]

requiredEnvVars.forEach((envVar) => {
  if (!process.env[envVar]) {
    throw new Error(`Missing required environment variable: ${envVar}`)
  }
})

module.exports = {
  env: process.env.NODE_ENV,
  port: process.env.PORT,
  mongoUri: process.env.MONGODB_URI,
  jwtSecret: process.env.JWT_SECRET,
  jwtExpire: process.env.JWT_EXPIRE || '7d'
}
```

## API Documentation Pattern

```javascript
// Use JSDoc for inline documentation
/**
 * @route   GET /api/users
 * @desc    Get all users with pagination
 * @access  Public
 * @query   {number} page - Page number (default: 1)
 * @query   {number} limit - Items per page (default: 10)
 * @query   {string} search - Search by name
 * @returns {Object[]} users - Array of user objects
 */
```

## Best Practices

1. **Always use async/await** - avoid callback hell
2. **Centralized error handling** - use error middleware
3. **Validate all inputs** - never trust client data
4. **Use environment variables** - never hardcode secrets
5. **Implement rate limiting** - prevent abuse
6. **Add request logging** - use morgan or winston
7. **Use HTTPS in production** - secure data in transit
8. **Sanitize database queries** - prevent NoSQL injection
9. **Implement proper CORS** - restrict origins in production
10. **Use compression** - reduce response size

## Common Pitfalls

❌ **Don't:** Forget to handle async errors
✅ **Do:** Use try-catch or async handler wrapper

❌ **Don't:** Return sensitive data (passwords, tokens)
✅ **Do:** Use .select() to exclude sensitive fields

❌ **Don't:** Use synchronous operations (fs.readFileSync)
✅ **Do:** Use async versions (fs.promises.readFile)

❌ **Don't:** Trust user input without validation
✅ **Do:** Validate and sanitize all inputs
