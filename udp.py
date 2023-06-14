import socket
import threading
import time
HOST_PORT = ("143.47.184.219", 5382)
SEQOUT = 0 # How many messages are sent that expect data to be received from the user
SEQIN = 0 # How many messages are received from another terminal
BITS = 6 
SENDLIST = [] # Buffer to store all the commands
ERROR = "ERROR!IN!CODE" # Sentinel value for ERRORs
BADCODE = "!BAAD!" # Sentinel value for bad headers
LOGIN = "" # Store the LOGIN username from the user
WHOCOUNTER = 0 # Store the amount of !who commands
SELFCOUNTER = 0 # Store the amount of commands that are sent to yourself
 

# send template message: SEND <user> <message>!seq!<seqNumber><checkSum>
# delivery templat message: DELIVERY <user> <message>!seq!<seqNumber><checkSum>
# Acknolwedgement message: DELIVERY <user> <message>!seq!<seqNumber>ACK<checkSum>


# Check if a received ack has the same sequence number has the message you sent, 
# Return True if that is the case(and the message is not sent to yourself), else return false
def checkSeq(receivedNum):
	message = SENDLIST[0].decode("utf-8")
	seqMark = message.find("!seq!")
	if seqMark == -1:
		return False
	seqNumStr = message[slice(seqMark + 5, len(message) - 5)] #seqNumStr = [SEND <user> <message>]!seq!<seqNumber>[<checkSum>]
	seqNum = int(seqNumStr, 10)
	if seqNum == receivedNum and LOGIN not in message: 
		# The LOGIN is not allowed to be in the message, since it uses SEQIN as its seqNumber and not SEQOUT(which we are looking for)
		return True

	return False

# Decrement the SEQOUT/seqNum of every SEND message(that is not yourself)
# This function is needed, since we can't change the commandList by simply decrementing SEQOUT. We have to manually change the messages in the array
def fixList():
	global SENDLIST

	for i, message in enumerate(SENDLIST):
		message = message.decode("utf-8")
		seqMark = message.find("!seq!")
		if seqMark == -1: # Not a SEND message so go back
			continue
		content = message[slice(message.find(" ") + 1, len(message))] # content = [SEND ]<user> <message> !seq!<seqNumber> <checkSum>
		userName = content[slice(0, content.find(" "))] # userName = <user>[ <message> !seq!<seqNumber> <checkSum>]
		if userName == LOGIN:
			# Message is sent to to yourself, so dont change the message
			continue

		ERRORCode = message[slice(len(message) - 5, len(message) - 1)] # ERRORCode = [SEND <user> <message>!seq!<seqNumber>] <checkSum>
		seqNumStr = message[slice(seqMark + 5, len(message) - 5)] # refer to checkSeq()
		seqNum = int(seqNumStr, 10)
		seqNum -= 1

		SENDLIST[i] = message[slice(0, seqMark)] + str(seqNum) + ERRORCode # Change the message in the SENDLIST command

# Send the first command of the list every x seconds
def send_command(sock):

	try:
		while True:
			time.sleep(5)
			command = ""
			if len(SENDLIST) > 0:
				command = SENDLIST[0]
				sock.sendto(command, HOST_PORT)	

	except OSError as msg:
		print(msg)
		quit()


# This function receives a package and looks at the checksum. if the whole message is valid it will return the package, else it will return an ERRORString
def receive(package):
	try:
			
		global SENDLIST, SEQOUT, WHOCOUNTER
		package = package.decode("utf-8")
		whoString = "WHO-OK " + LOGIN

		# Check for headers, what type of message etc. Only SEND messages are important/get deconstructed

		if package == whoString:
			del SENDLIST[0]
			return package

		if "SET-OK" in package or "SEND-OK" in package:
			return ERROR

		if package == "BAD-RQST-BODY" or package == "BAD-RQST-HDR":
			return BADCODE

		ERRORID = package[slice(len(package) - 4, len(package))]

		message = package[slice(0, len(package) - 4)][9:] # [DELIVERY ]<user> <message>!seq!<seqNumber><checkSum>
		message = message[slice(message.find(" ") + 1, len(message))] # [<user> ]<message>!seq!<seqNumber><checkSum>
		startSeq = message.find("!seq!")

		if package == "UNKNOWN":
			# Our seqNum/SEQOUT of our commands will be 1 too high if we dont fix anything when a message is sent to an unknown user
			# Thus decrement SEQOUT and also change the commandList
			# Also remove the command, since we will never get an acknowledgement for it
			SEQOUT -= 1
			fixList()
			del SENDLIST[0]
			print("User is not logged in")
			print("Enter command: ")
			return ERROR
		if startSeq == -1:
			return ERROR

		# This is nothing too important, basic checkSum
		# Message is split into equal 4 BITS (and a remainder of < 4 if the message is not equally splittable)
		# Message is converted in hexadecimals, so they will look like this: 0xFFFF (the "0x" part is the reason for having to use [2:] in the string manipulation)
		messageList = []
		message = message.encode("utf-8").hex()

		message = hex(int(message, 16))[2:]
		for index in range(0, len(message), 4):
			messageList.append(message[index : index + 4])

		BITSum = "0"
		for frame in messageList:

			BITSum = int(BITSum, 16)
			frameBITS = int(frame, 16)
			codeWord = hex(frameBITS + BITSum)

			if len(codeWord) > BITS:
				while len(codeWord) > BITS:
					carry = codeWord[2]
					codeWord = hex(int(codeWord[3:], 16) + int(carry, 16))

			BITSum = codeWord

		try: 
			finalMessage = hex(int(codeWord, 16) + int(ERRORID, 16))
		except ValueError:
			# SET FLIP sometimes does funny things by adding characters randomly in your message, so using int(string, 16) will give you a ValueERROR
			# This means that the code is invalid so you can just return an ERRORString
			return ERROR

		codeWord = finalMessage[2:]

		for char in codeWord:
			if char != "f":
				return ERROR

		package = package[slice(0, len(package) - 4)]
		return package

	except UnicodeDecodeError:
		# SET burst sometimes does funny things as well, so you can't decode a message with utf-8 because there are characters that shouldnt be allowed in the message.
		# This means return an ERROR again
		return ERROR

# Add seqNum to a message and add a checkSum to it. This message will be sent to the server
def send(message):

	try:

		content = message.decode("utf-8")[5:]
		user = content[slice(0, content.find(" "))]
		content = content[slice(content.find(" ") + 1, len(content))]

		seqNum = SEQOUT - WHOCOUNTER - SELFCOUNTER
		if user == LOGIN:
			seqNum = SEQIN
		if "ACK" not in content:
			content = content +  "!seq!" + str(seqNum)

		messageList = []
		message = content
		message = message.encode("utf-8").hex()
		
		for index in range(0, len(message), 4):
			fragment = message[index : index + 4]
			messageList.append(fragment)
		codeWord = ""

		BITSum = "0"
		for frame in messageList:

			BITSum = int(BITSum, 16)
			frameBITS = int(frame, 16)
			codeWord = hex(frameBITS + BITSum)
			
			if len(codeWord) > BITS:
				while len(codeWord) > BITS:
					carry = codeWord[2]
					codeWord = hex(int(codeWord[3:], 16) + int(carry, 16))

			BITSum = codeWord

		codeWord = codeWord[2:]

		while len(codeWord) < BITS - 2: 
			codeWord = "0" + codeWord

		codeWord = hex((int(codeWord, 16)) ^ 0xFFFF)[2:]
		
		package = ("SEND " + user + " " + content + (codeWord) + "\n").encode("utf-8")  
		return package
	
	except OSError as msg:
		print(msg)
		quit()

def receive_data(sock):

	try:
		while True:
			global SEQOUT, SENDLIST, SEQIN, LOGIN, ackMessage, SELFCOUNTER
			data = sock.recv(4096)
			if not data:
				print("no data")
			else:
				data = data.strip()
				received = receive(data) # ERROR Check

				if  received == ERROR: 
					continue
				elif received == BADCODE:
					print("Illegal command")
					print("Enter command: ")
					del SENDLIST[0]
					continue

				message = received

				if "ACK" in message:
					seqNum = message[slice(message.find("!seq!") + 5, len(message) - 3)] 
					seqNum = int(seqNum, 10)
					# - 1 is to account for incrementing SEQOUT after appending it to the List
					if seqNum == (SEQOUT - WHOCOUNTER - SELFCOUNTER - 1):
						# This means that we have received an acknowledgement from something we sent
						if not checkSeq(seqNum):
							continue
						del SENDLIST[0]
				else:

					if "WHO-OK" in message:
						print(f"All the users: {message[7:]}")
						print("Enter command: ")
						continue
				
					if "DELIVERY" in message:
						seqNum = message[slice(message.find("!seq!") + 5, len(message))] 
						message = message[slice(0, message.find("!seq!"))]
						seqNum = int(seqNum, 10)

						userName = message[slice(message.find(" ") + 1, len(message))]
						userName = userName[slice(0, userName.find(" "))]
						toSend = ("SEND " + userName + " " + "!seq!" + str(seqNum) + "ACK").encode("utf-8")

						if seqNum == SEQIN:
							print(f"Delivered: {message}")
							print("Enter command: ")
							if userName == LOGIN:
								del SENDLIST[0]
								continue
							ackMessage = send(toSend)
							sock.sendto(ackMessage, HOST_PORT)
							SEQIN += 1
						
						elif seqNum == SEQIN - 1 and "DELIVERY" in message:
							# Send acknowledgement again if the other terminal hasn't received the acknowledgement for their previously sent message
							if userName == LOGIN:
								continue
							ackMessage = send(toSend)
							sock.sendto(ackMessage, HOST_PORT)

	except OSError as msg:
		print(msg)
		quit()

def insert_commands(sock):
	try:
		global SEQOUT, SENDLIST, WHOCOUNTER, SELFCOUNTER

		#  Use ERRORs Commands to test here

		# sock.sendto("SET DROP 0.2\n".encode("utf-8"), HOST_PORT) #done
		# sock.sendto("SET FLIP 0.001\n".encode("utf-8"), HOST_PORT) #done
		# sock.sendto("SET BURST 0.5\n".encode("utf-8"), HOST_PORT) #done
		# sock.sendto("SET BURST-LEN 3 5\n".encode("utf-8"), HOST_PORT) #done
		# sock.sendto("SET DELAY 1\n".encode("utf-8"), HOST_PORT) #done
		# sock.sendto("SET DELAY-LEN 3 5\n".encode("utf-8"), HOST_PORT) #done

		while True:
			print("Enter command: ")
			command = input()
			if command == "!quit":
				quit()

			elif command == "!who":
				currMessage = ("WHO\n").encode("utf-8")
				SEQOUT += 1
				WHOCOUNTER += 1
				SENDLIST.append(currMessage)

			elif command.startswith("@"):
				command = command.replace("@", "")
				userName = command[slice(command.find(" "))]
				userMessage = command[slice(command.find(" ") + 1, len(command), 1)]

				currMessage = ("SEND " + userName + " " + userMessage).encode("utf-8")

				if userName == LOGIN:
					SELFCOUNTER += 1
				
				currMessage = send(currMessage)
				SENDLIST.append(currMessage)
				SEQOUT += 1
			else:
				print("Illegal command")
				continue
	except OSError as msg:
		print(msg)
		quit()

def main():

		while True:
			sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			userName = input("Enter your username: ")
			global LOGIN
			LOGIN = userName
			message = ("HELLO-FROM " + userName + "\n").encode("utf-8")
			sock.sendto(message, HOST_PORT)

			buffer = ""
			while(True):
				data = sock.recv(4096).decode("utf-8")
				if "\n" not in data or "" not in data:
						buffer += data
						continue
				buffer += data
				break
			data = buffer.strip()
			print(data)
			if(data == "IN-USE"):
					print("Name is already taken, use another name")
					continue

			elif data == "BUSY":
					print("Maximum number of clients has been reached, try again next time")
					continue

			elif data == "BAD-RQST-BODY" or data == "BAD-RQST-HDR":
					print("Wrong command")
					continue

			elif data == f"HELLO {userName}":
					getData = threading.Thread(target=receive_data, args=(sock, ), daemon=True)
					getData.start()
					sendThread = threading.Thread(target=send_command, args=(sock, ), daemon=True)
					sendThread.start()
					insert_commands(sock)

			else:
					print("something happened, package lost?")
					continue
				

main()