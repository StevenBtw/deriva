-- File Type Registry
-- Exported from current database
-- Total entries: 46


-- ASSET
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.jpg', 'asset', 'image');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.png', 'asset', 'image');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.svg', 'asset', 'image');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.ttf', 'asset', 'font');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.woff', 'asset', 'font');

-- BUILD
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('dockerfile', 'build', 'docker');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('makefile', 'build', 'make');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('pom.xml', 'build', 'maven');

-- CONFIG
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.env', 'config', 'env');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.ini', 'config', 'ini');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.json', 'config', 'json');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.toml', 'config', 'toml');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.xml', 'config', 'xml');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.yaml', 'config', 'yaml');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.yml', 'config', 'yaml');

-- DATA
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.csv', 'data', 'csv');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.parquet', 'data', 'parquet');

-- DEPENDENCY (package/dependency manifest files - matched by full filename)
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('requirements.txt', 'dependency', 'python');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('setup.py', 'dependency', 'python');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('setup.cfg', 'dependency', 'python');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('pyproject.toml', 'dependency', 'python');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('package.json', 'dependency', 'javascript');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('package-lock.json', 'dependency', 'javascript');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('yarn.lock', 'dependency', 'javascript');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('go.mod', 'dependency', 'golang');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('go.sum', 'dependency', 'golang');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('Cargo.toml', 'dependency', 'rust');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('Cargo.lock', 'dependency', 'rust');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('Gemfile', 'dependency', 'ruby');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('Gemfile.lock', 'dependency', 'ruby');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('composer.json', 'dependency', 'php');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('composer.lock', 'dependency', 'php');

-- DOCS
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.md', 'docs', 'markdown');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.rst', 'docs', 'restructuredtext');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.txt', 'docs', 'text');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.adoc', 'docs', 'asciidoc');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.markdown', 'docs', 'markdown');

-- EXCLUDE
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.git', 'exclude', 'vcs');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.venv', 'exclude', 'virtualenv');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('__pycache__', 'exclude', 'cache');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('build', 'exclude', 'build');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('dist', 'exclude', 'build');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('node_modules', 'exclude', 'dependencies');

-- SOURCE
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.c', 'source', 'c');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.cpp', 'source', 'cpp');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.cs', 'source', 'csharp');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.css', 'source', 'stylesheet');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.go', 'source', 'golang');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.html', 'source', 'html');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.java', 'source', 'java');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.js', 'source', 'javascript');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.php', 'source', 'php');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.py', 'source', 'python');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.rb', 'source', 'ruby');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.rs', 'source', 'rust');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.scss', 'source', 'stylesheet');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.sh', 'source', 'shell');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.sql', 'source', 'sql');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.ts', 'source', 'typescript');

-- TEST (wildcard patterns - matched using fnmatch)
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('*.spec.js', 'test', 'javascript');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('*.test.js', 'test', 'javascript');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('*_test.py', 'test', 'python');
INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('test_*.py', 'test', 'python');
