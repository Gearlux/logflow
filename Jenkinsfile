pipeline {
    agent any

    environment {
        // Local virtual environment within the Jenkins workspace for portability
        VENV_PATH = "${WORKSPACE}/.venv"
        VENV_BIN = "${VENV_PATH}/bin"
    }

    stages {
        stage('Initialize') {
            steps {
                echo 'Creating Isolated Virtual Environment...'
                sh "python3 -m venv ${VENV_PATH}"
                
                echo 'Installing Dependencies in Editable Mode...'
                sh "${VENV_BIN}/pip install --upgrade pip"
                sh "${VENV_BIN}/pip install -e .[dev]"
            }
        }

        stage('Linting') {
            parallel {
                stage('Black') {
                    steps {
                        sh "${VENV_BIN}/black --check logflow tests examples"
                    }
                }
                stage('Isort') {
                    steps {
                        sh "${VENV_BIN}/isort --check-only logflow tests examples"
                    }
                }
                stage('Flake8') {
                    steps {
                        // Clean up previous reports
                        sh "rm -f flake8.txt flake8-report.xml"
                        // Use || true to prevent the stage from stopping before the report is generated
                        sh "${VENV_BIN}/flake8 logflow tests examples --tee --output-file=flake8.txt || true"
                        // Convert report to JUnit XML
                        sh "if [ -f flake8.txt ]; then ${VENV_BIN}/flake8_junit flake8.txt flake8-report.xml; fi"
                    }
                    post {
                        always {
                            // Archive the report if it was generated
                            junit allowEmptyResults: true, testResults: 'flake8-report.xml'
                        }
                    }
                }
            }
        }

        stage('Type Check') {
            steps {
                sh "${VENV_BIN}/mypy logflow tests examples"
            }
        }

        stage('Unit Tests') {
            steps {
                sh "${VENV_BIN}/pytest tests --junitxml=test-report.xml --cov=logflow --cov-report=xml:coverage.xml --cov-report=term"
            }
            post {
                always {
                    // Archive and display JUnit test results
                    junit allowEmptyResults: true, testResults: 'test-report.xml'
                    
                    // Display Coverage in Jenkins UI using Code Coverage API Plugin
                    recordCoverage tools: [[parser: 'COBERTURA', pattern: 'coverage.xml']]
                }
            }
        }

    }

    post {
        always {
            echo 'LogFlow Pipeline Complete.'
        }
        success {
            echo 'Project is healthy and ready for publication.'
        }
        failure {
            echo 'Build failed. Please check linting or test failures.'
        }
    }
}
