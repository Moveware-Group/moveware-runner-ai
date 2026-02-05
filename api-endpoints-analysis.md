# MoveConnect Online Access - API Endpoints Analysis

## Overview
This document contains all API endpoints extracted from the MoveConnect Online Access application (`moveconnect-online-access-0a6283b0e8fb.zip`). The application is an Angular-based frontend that communicates with backend REST APIs to populate customer-facing pages with data.

---

## Base URLs by Environment

### Development/Test Environment
- **API Root**: `https://rest.moveconnect.com/malcolm-test/v1`
- **Static Assets**: `https://static.moveware-test.app`

### UAT Environment
- **API Root**: `https://rest.moveconnect.com/malcolm-uat/v1`
- **Static Assets**: `https://static.moveware.app`

### Production Environment
- **API Root**: `https://rest.moveconnect.com/malcolm-api/v1`
- **Static Assets**: `https://static.moveware.app`

---

## Core API Endpoints

### 1. Metadata Endpoints

#### Get Page Metadata
**Purpose**: Retrieves page configuration, theme settings, translations, and UI metadata for rendering customer-facing pages.

**URL Pattern**:
```
GET {FETCH_API_ROOT}/company/{companyId}/page/{pageType}
GET {FETCH_API_ROOT}/company/{companyId}/page/{pageType}/{mdVersion}
```

**Parameters**:
- `companyId` (path) - Company identifier
- `pageType` (path) - Type of page being requested
- `mdVersion` (path, optional) - Specific metadata version
- `brand` (query, optional) - Brand identifier for white-labeling

**Query Parameters** (metadata-specific):
- `brand` - Brand customization identifier

**Response Contains**:
- Page theme configuration
- Page title and favicon
- UI component metadata
- Internationalization (i18n) settings
- Page structure and layout configuration

**Example URLs**:
- `/company/alextest/page/customer-quote`
- `/company/alextest/page/customer-booking-confirmation`
- `/company/alextest/page/customer-performance-review`
- `/company/alextest/page/customer-payment-invoice`
- `/company/alextest/page/customer-document-request`

---

### 2. Data Endpoints

#### Get Page Data
**Purpose**: Retrieves actual business data to populate the page (job details, quotes, invoices, etc.).

**URL Pattern**:
```
GET {FETCH_API_ROOT}/company/{companyId}/page/{pageType}/data
GET {FETCH_API_ROOT}/company/{companyId}/page/{pageType}/data/{dataTag}
```

**Parameters**:
- `companyId` (path) - Company identifier
- `pageType` (path) - Type of page (e.g., customer-quote, customer-payment-invoice)
- `dataTag` (path, optional) - Specific data tag for targeted data retrieval

**Query Parameters** (data-specific):
- `token` (or `t`) - Security token for authentication
- `jobId` (or `j`) - Job identifier
- `customerId` (or `cu`) - Customer identifier
- `invoiceId` (or `in`) - Invoice identifier
- `gatewayId` (or `p`) - Payment gateway identifier
- `configId` (or `p`) - Configuration identifier
- `po-version` - Page object version parameter

**Response Contains**:
- Job/quote details
- Pricing information
- Customer information
- Invoice data
- Payment information
- Document lists

**Example Data Structure** (from test data):
```json
{
  "job_ref": "100899",
  "price_options": {
    "opt_1_total_price": "A$616.18",
    "opt_1_table_details": [...],
    "opt_1_sub_total": "A$560.16",
    "opt_1_tax": "A$56.02"
  }
}
```

---

#### Post Data to Endpoint
**Purpose**: Submits form data, payments, confirmations, and other user actions.

**URL Pattern**:
```
POST/PUT/PATCH {FETCH_API_ROOT}/company/{companyId}/page/{pageType}/data
POST/PUT/PATCH {FETCH_API_ROOT}/company/{companyId}/page/{pageType}/data/{tag}
```

**HTTP Methods**: 
- Supports multiple sequential methods: `POST`, `PUT`, `PATCH`
- Can execute multiple methods in sequence (e.g., "POST,PUT")

**Parameters**:
- `companyId` (path) - Company identifier
- `pageType` (path) - Type of page
- `tag` (path, optional) - Specific data tag/action
- Same query parameters as GET data endpoint

**Request Headers**:
```
Content-Type: application/json
Cache-Control: no-cache
Accept: application/json
```

**Request Body**:
- Form data (JSON format)
- User inputs and selections
- Payment information
- Signatures and documents

**Response Paths** (configurable):
- `status` - Response status code path
- `error` - Error message path
- `redirectURL` - URL for client-side redirect
- `navigateURL` - URL for navigation
- `downloadSrc` - Download source URL
- `tagRefresh` - Tag to refresh after action

---

### 3. File Management Endpoints

#### Get Files List
**Purpose**: Retrieves list of files associated with a job/quote/customer.

**URL Pattern**:
```
GET {FETCH_API_ROOT}/company/{companyId}/page/{pageType}/files
```

**Parameters**:
- `companyId` (path) - Company identifier
- `pageType` (path) - Type of page
- Query parameters same as data endpoints (token, jobId, etc.)

---

#### Add Files
**Purpose**: Uploads files to be associated with a job/quote/customer.

**URL Pattern**:
```
POST {FETCH_API_ROOT}/company/{companyId}/page/{pageType}/files/add
```

**Parameters**:
- `companyId` (path) - Company identifier
- `pageType` (path) - Type of page
- Query parameters same as data endpoints

**Request Type**: Multipart file upload

---

#### Remove Files
**Purpose**: Removes/deletes files associated with a job/quote/customer.

**URL Pattern**:
```
DELETE/POST {FETCH_API_ROOT}/company/{companyId}/page/{pageType}/files/remove
```

**Parameters**:
- `companyId` (path) - Company identifier
- `pageType` (path) - Type of page
- Query parameters same as data endpoints

---

### 4. Static Assets Endpoints

#### Get Company Assets
**Purpose**: Retrieves company-specific static assets (logos, images, branding files).

**URL Pattern**:
```
GET {FETCH_ASSETS}/{companyId}
GET {FETCH_ASSETS}/{companyId}/{brand}
```

**Parameters**:
- `companyId` (path) - Company identifier
- `brand` (path, optional) - Brand identifier for white-labeled assets

---

#### Get Template Files
**Purpose**: Retrieves template files for specific brands.

**URL Pattern**:
```
GET {FETCH_API_ROOT}/company/{companyId}/brand/{brand}/file
```

**Parameters**:
- `companyId` (path) - Company identifier
- `brand` (path) - Brand identifier

---

## Page Types (Known from Tests)

The following page types have been identified in the codebase:

1. **customer-quote** - Customer quote viewing and acceptance
2. **customer-booking-confirmation** - Booking confirmation page
3. **customer-performance-review** - Performance review submission
4. **customer-payment-invoice** - Invoice payment processing
5. **customer-document-request** - Document request handling

---

## Query Parameter Mapping

The application supports both full and abbreviated query parameters:

| Abbreviated | Full Parameter | Description |
|-------------|---------------|-------------|
| `e` | `companyId` | Company identifier (legacy routing) |
| `f` | `pageType` | Page type (legacy routing) |
| `cu` | `customerId` | Customer identifier |
| `in` | `invoiceId` | Invoice identifier |
| `j` | `jobId` | Job identifier |
| `p` | `gatewayId` / `configId` | Payment gateway/config identifier |
| `t` | `token` | Authentication token |

---

## Authentication & Security

### Token-Based Authentication
- All data endpoints require a `token` query parameter
- Token is used for authentication and authorization
- Token values are partially hidden in logs (last 4 characters visible)

### Security Features
- CORS headers configured
- Cache-Control headers on POST requests
- Token sanitization in error logs and monitoring
- Signature data obfuscation (last 15 characters visible in logs)

---

## Monitoring & Telemetry

### Application Insights Integration
- **Instrumentation Key**: `f4f342d0-b9e4-4982-a6d6-aa25dcbf29cc`
- Logs page views, exceptions, and custom events
- Tracks form submissions with sanitized data

### Logged Events
- Page views (`OnlineAccess`)
- Form submissions (`Submit form`)
- API errors and exceptions
- Request timing and performance metrics

---

## SDK Integration

The application uses `@moveconnect/sdk` version 1.0.79, which provides:

- **DataModelService** - Query parameter string building
- **MonitoringService** - Exception and event logging
- **UtilsService** - Value hiding and data manipulation
- **ThemeService** - Theme management

The SDK likely handles additional internal API calls not directly visible in the application code.

---

## URL Routing Structure

### Modern Format
```
/rms/{companyId}/{pageType}?{queryParams}
```

### Legacy Format (Auto-redirected)
```
/?e={companyId}&f={pageType}&cu={customerId}&j={jobId}&t={token}
```

The application automatically converts legacy format to modern format and redirects.

---

## Error Handling

### Error Responses
- HTTP status codes are checked (200-299 = success)
- Custom error messages for:
  - Status 0: "Unable to connect"
  - 404: Metadata/data not found
  - Other errors: Specific error messages from response body

### Error Logging
All errors are sent to monitoring service with:
- Error message
- Error name
- HTTP status and status text
- Request URL (with token sanitized)

---

## Summary

The MoveConnect Online Access platform uses a RESTful API structure with the following main categories:

1. **Metadata APIs** - Page configuration and UI structure
2. **Data APIs** - Business data (jobs, quotes, invoices, payments)
3. **File APIs** - File upload, download, and management
4. **Asset APIs** - Static assets and branding

All endpoints follow a consistent pattern:
```
{BASE_URL}/company/{companyId}/page/{pageType}/{resource}?{queryParams}
```

The platform supports multiple environments (test, UAT, production) with environment-specific base URLs and handles both modern and legacy URL formats for backward compatibility.
